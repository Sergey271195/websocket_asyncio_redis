import asyncio
import websockets
import aioredis
import os
import json
import aiohttp
import random
from datetime import datetime, timedelta
import functools
import speech_recognition as sr
from threading import Thread
import time
from decoder import TextDecoder, HELP_MESSAGE
import re
from customTg import createRowKeyboard

DEBUG  = (os.environ.get('DEBUG') == 'True')

if DEBUG:
    REDIS_TOKEN = 'redis://localhost:6379'
else:
    REDIS_TOKEN = os.environ.get('REDIS_TOKEN')

class SpeechRecognitionThread(Thread):

    def __init__(self, audio_file, message_queue, decode_queue, user_id):
        super().__init__()
        self.audio_file = audio_file
        self.message_queue = message_queue
        self.user_id = user_id
        self.decode_queue = decode_queue

    def run(self):
        audio_data = sr.AudioData(self.audio_file, 48000, 2)
        recognizer = sr.Recognizer()
        try:
            transcribed_data = recognizer.recognize_google(audio_data, language = 'ru-RU')
            print("Google Speech Recognition thinks you said " + transcribed_data)
            self.decode_queue.put_nowait((transcribed_data, self.user_id))
            return(transcribed_data)
        except sr.UnknownValueError:
            print("Google Speech Recognition could not understand audio")
            self.message_queue.put_nowait(('Google Speech Recognition could not understand audio', self.user_id))

        except sr.RequestError as e:
            print("Could not request results from Google Speech Recognition service; {0}".format(e))
            self.message_queue.put_nowait(('Could not request results from Google Speech Recognition service', self.user_id))



class AsyncTelegramListener():

    def __init__(self):
        
        self.TOKEN = os.environ.get('REMINDME_TOKEN')
        self.URL = f'https://api.telegram.org/bot{self.TOKEN}'
        self.SEND_MESSAGE_URL = os.path.join(self.URL, 'sendMessage')
        self.MESSAGE_DELAY = 300 ### 5 minutes
        self.SEND_MESSAGE_INTERVAL = 120 ### 2 minutes before and after
        self.REDIS_TOKEN = REDIS_TOKEN

    async def redis_connection_listener(self, request_interval):

        redis = await aioredis.create_redis_pool(self.REDIS_TOKEN, encoding="utf-8")
        session = aiohttp.ClientSession()
        while True:
            users = await redis.smembers('users')
            for user in users:
                first_task = await redis.zrange(user, 0, 0)
                all_tasks = await redis.zrange(user, 0, -1)

                if first_task:
                    try:
                        time, task = first_task[0].split('.')
                        time_delta =  int(time) - int(datetime.now().timestamp())
                        if abs(time_delta) < self.SEND_MESSAGE_INTERVAL:
                            print('Send message to user', user)
                            message_to_send = f'You asked us to remind you about: {task}'
                            await redis.zrem(user, first_task[0])
                            try:
                                async with session.post(self.SEND_MESSAGE_URL, data= {'chat_id': user, 'text': message_to_send}) as response:
                                    print(response.status)
                                    if response.status == 200:
                                        print('Success')
                                    else:
                                        print(f'Message for user {user} was delayed')
                                        delay = int(time) + self.MESSAGE_DELAY
                                        await redis.zadd(user, delay, task)
                            except Exception as e:
                                print(e)
                        elif time_delta < -200:
                            await redis.zrem(user, first_task[0])
                            print('Delte unsend message. Time expired')
                        else:
                            pass
                    except Exception as e:
                        print(e)

            await asyncio.sleep(request_interval)

        await redis.wait_closed()




class AsyncWebsocketListener():

    def __init__(self, test_queue, voice_queue, message_queue, decode_queue, keyboard_queue, reply_queue):
        self.session = aiohttp.ClientSession()
        self.TOKEN = os.environ.get('REMINDME_TOKEN')
        self.URL = f'https://api.telegram.org/bot{self.TOKEN}'
        self.SEND_MESSAGE_URL = os.path.join(self.URL, 'sendMessage')
        self.MESSAGE_DELAY = 300 ### 5 minutes
        self.SEND_MESSAGE_INTERVAL = 120 ### 2 minutes before and after
        self.REDIS_TOKEN = REDIS_TOKEN
        self.voice_queue = voice_queue
        self.message_queue = message_queue
        self.decode_queue = decode_queue
        self.test_queue = test_queue
        self.keyboard_queue = keyboard_queue
        self.reply_queue = reply_queue
        self.start_converters()

    def start_converters(self):
        for i in range(5):
            loop = asyncio.get_event_loop()
            task = loop.create_task(self.voice_converter(self.voice_queue))
            #decode_task = loop.create_task(self.text_decoder(self.decode_queue))
            message_task = loop.create_task(self.message_sender(self.message_queue))
            decode_task = loop.create_task(self.test_decoder(self.decode_queue))
            keyboard_tasks = loop.create_task(self.keyboard_message_sender(self.keyboard_queue))
            reply_tasks = loop.create_task(self.reply_message_handler(self.reply_queue))


    async def reply_message_handler(self, queue):
        while True:
            redis = await aioredis.create_redis_pool(self.REDIS_TOKEN, encoding="utf-8")
            user_id, data = await queue.get()
            split_data = data.split('.')
            if split_data[0] == 'add':
                await redis.zadd(user_id, int(split_data[1]), split_data[1]+'.'+split_data[2])
                await self.message_queue.put((f'New reminder has been set', user_id))
            elif split_data[0] == 'remove':
                await redis.zremrangebyrank(user_id, int(split_data[1]), int(split_data[1]))
                await self.message_queue.put((f'The task has been deleted!', user_id))
            elif split_data[0] == 'move':
                await redis.zremrangebyrank(user_id, int(split_data[1]), int(split_data[1]))
                await redis.zadd(user_id, int(split_data[2]), f'{split_data[2]}.{split_data[3]}')
                await self.message_queue.put((f'The task has been shifted!', user_id))
            elif split_data[0] == 'alter':
                await redis.zremrangebyrank(user_id, int(split_data[1]), int(split_data[1]))
                await redis.zadd(user_id, int(split_data[2]), f'{split_data[2]}.{split_data[3]}')
                await self.message_queue.put((f'The task has been altered!', user_id))
            queue.task_done()
            await redis.wait_closed()

    async def message_sender(self, queue):
        while True:
            reply_message, user_id = await queue.get()
            async with self.session.post(self.SEND_MESSAGE_URL, data= {'chat_id': user_id, 'text': reply_message}) as response:
                r = await response.json()
                if response.status == 200:
                    queue.task_done()
                else:
                    await asyncio.sleep(10)
                    await queue.put((reply_message, user_id))

    async def keyboard_message_sender(self, queue):
        while True:
            reply_message, user_id, reply_markup = await queue.get()
            async with self.session.post(self.SEND_MESSAGE_URL, data= {'chat_id': user_id, 'text': reply_message, 'reply_markup': reply_markup}) as response:
                r = await response.json()
                if response.status == 200:
                    queue.task_done()
                else:
                    await asyncio.sleep(10)
                    await queue.put((reply_message, user_id))

    async def text_decoder(self, queue):
        while True:
            message, user_id = await queue.get()
            decoder = TextDecoder().main_parser(message)
            if decoder == 'list':
                print('User is asking for list of tasks')
                await self.redis_list_returner(user_id)
            elif decoder:
                time, task = decoder                
                reply_date = time.strftime('%d.%m.%y')
                reply_time = time.strftime('%H:%M')
                await self.message_queue.put((f' Reminder set to {reply_date} {reply_time}', user_id))
                await self.redis_manager(user_id, time.timestamp(), task)
                
            else:
                await self.message_queue.put(('We were not able to create task from your request', user_id))

    async def test_decoder(self, queue):
        while True:
            message, user_id = await queue.get()
            decoder = TextDecoder().main_parser(message)

            if decoder:
                redis = await aioredis.create_redis_pool(self.REDIS_TOKEN, encoding="utf-8")
                number_of_tasks = await redis.zcard(user_id)
                command_type = decoder.get('type')
                if command_type == 'add':

                    show_time = decoder.get('time').strftime('%H:%M %d.%m.%y')
                    show_task = decoder.get('task')
                    await self.keyboard_queue.put((f'Set task "{show_task}" to {show_time} ?', user_id, createRowKeyboard([(str(int(decoder.get('time').timestamp()))+'.'+decoder.get('task'), 'Yes'), ('no', 'No')])))

                elif command_type == 'list':
                    if number_of_tasks == 0:
                        await self.message_queue.put((f'No current tasks waiting to be completed', user_id))
                    else:
                        period = decoder.get('period') 
                        if period:
                            return_list = await redis.zrangebyscore(user_id, period[0], period[1])
                            if return_list:
                                start_index = await redis.zrank(user_id, return_list[0])
                                list_title = datetime.fromtimestamp(int(period[0])).strftime('%d.%m.%y')
                            else:
                                await self.message_queue.put((f'No tasks for specified date', user_id))
                                list_title = ''
                        else:
                            return_list = await redis.zrange(user_id, 0, -1)
                            start_index = 0
                            list_title = 'Full list'

                        reply_meassge = list_title + '\n'  
                        for index, entry in enumerate(return_list):
                            task = entry.split('.')[1]
                            if period:
                                time = datetime.fromtimestamp(int(entry.split('.')[0])).strftime('%H:%M')
                            else:
                                try:
                                    time = datetime.fromtimestamp(int(entry.split('.')[0])).strftime('%d.%m.%y %H:%M')
                                except Exception as e:
                                    time = 'Error'
                            reply_meassge += str(index+1)+') ' + time + ' ' + task.capitalize() + ' {'+str(index+start_index+1)+'}\n'
                        await self.message_queue.put((f'{reply_meassge}', user_id))
                
                elif command_type == 'alter':
                    key = int(decoder.get('key')) - 1
                    if key <= number_of_tasks and number_of_tasks != 0:
                        new_task = decoder.get('task')
                        old_task = await redis.zrange(user_id, key, key)
                        remaining_timestamp = old_task[0].split('.')[0]
                        old_task_text = old_task[0].split('.')[1]
                        await self.keyboard_queue.put((f'Alter task "{old_task_text}" to "{new_task}" ?', user_id, createRowKeyboard([(str(key)+'.'+str(int(remaining_timestamp))+'.'+new_task, 'Yes'), ('no', 'No')])))
                    else:
                        await self.message_queue.put((f'Task with key {key} doesn\'t exist', user_id))

                elif command_type == 'remove':
                    key = int(decoder.get('key')) - 1
                    if key <= number_of_tasks and number_of_tasks != 0:
                        task_to_delete = await redis.zrange(user_id, key, key)
                        task_text = task_to_delete[0].split('.')[1]
                        await self.keyboard_queue.put((f'Delete task "{task_text}" ?', user_id, createRowKeyboard([(str(key), 'Yes'), ('no', 'No')])))
                    else:
                        await self.message_queue.put((f'Task with key {key} doesn\'t exist', user_id))

                elif command_type == 'move' and number_of_tasks != 0:
                    key = int(decoder.get('key')) - 1
                    if key <= number_of_tasks:
                        task_to_move = await redis.zrange(user_id, key, key)
                        task_text = task_to_move[0].split('.')[1]
                        new_time = decoder.get('time')
                        if isinstance(new_time, timedelta):
                            previous_time = datetime.fromtimestamp(int(task_to_move[0].split('.')[0]))
                            move_time = (datetime(previous_time.year, previous_time.month, previous_time.day) + new_time)
                            time_to_message = move_time.strftime('%d.%m.%y %H:%M')
                            time_for_redis = int(move_time.timestamp())
                        else:
                            time_to_message = datetime.fromtimestamp(decoder.get('time')).strftime('%d.%m.%y %H:%M')
                            time_for_redis = decoder.get('time')
                        await self.keyboard_queue.put((f'Shift task "{task_text}" to {time_to_message}?', user_id, createRowKeyboard([(str(key)+'.'+str(time_for_redis)+'.'+task_text, 'Yes'), ('no', 'No')])))
                    else:
                        await self.message_queue.put((f'Task with key {key} doesn\'t exist', user_id))


                elif command_type == 'help':
                    await self.message_queue.put((HELP_MESSAGE, user_id))
                
                elif command_type == 'error':
                    error_message = decoder.get('message')
                    await self.message_queue.put((error_message, user_id))
                    

                await asyncio.sleep(1)    
                queue.task_done()
                await redis.wait_closed()

            else:
                await self.message_queue.put((f'Мы не поняли ваш запрос', user_id))

    async def redis_manager(self, user_id, time, task):

        redis = await aioredis.create_redis_pool(self.REDIS_TOKEN)
        await redis.sadd('users', user_id)
        await redis.zadd(str(user_id), int(time), f'{int(time)}.{task}')
        await redis.wait_closed()

    
    async def redis_list_returner(self, user_id):

        redis = await aioredis.create_redis_pool(self.REDIS_TOKEN, encoding="utf-8")
        task_list = await redis.zrange(user_id, 0, -1)
        if task_list:
            task_list = [(task.split('.')) for task in task_list]
            return_task_list = [(datetime.fromtimestamp(int(task[0])).strftime('%d.%m.%y %H:%M'), task[1]) for task in task_list]
            reply_message = ''
            for index, task in enumerate(task_list):
                task_time = datetime.fromtimestamp(int(task[0])).strftime('%d.%m.%y %H:%M')
                reply_message += f'{index+1}) {task_time} ----> {task[1]}\n'
            await self.message_queue.put((reply_message, user_id))
        else:
            await self.message_queue.put(('В списке заданий покати шаром', user_id))
        await redis.wait_closed()


    async def voice_producer(self, user_id, file_id):
        print(user_id, file_id, 'Voice message')
        file_path = f'https://api.telegram.org/bot{self.TOKEN}/getFile?file_id={file_id}'
        
        async with self.session.get(file_path) as response:
            r = await response.json()
            if response.status == 200:
                link = r['result'].get('file_path')
                download_link = f'https://api.telegram.org/file/bot{self.TOKEN}/{link}'
                await self.voice_queue.put([download_link, user_id])

    async def voice_converter(self, voice_queue):
        while True:
            download_link, user_id = await voice_queue.get()
            proc = await asyncio.create_subprocess_shell(
                f'ffmpeg -i {download_link} -f wav -',
                stdout=asyncio.subprocess.PIPE
                )
            stdout, stderr = await proc.communicate()
            thread = SpeechRecognitionThread(stdout, self.message_queue, self.decode_queue, user_id)
            thread.start()
            voice_queue.task_done()

    
async def main(websocket, path):

        message_queue = asyncio.Queue()
        test_queue = asyncio.Queue()
        voice_queue = asyncio.Queue()
        decode_queue = asyncio.Queue()
        keyboard_queue = asyncio.Queue()
        reply_queue = asyncio.Queue()


        listener = AsyncWebsocketListener(test_queue, voice_queue, message_queue, decode_queue, keyboard_queue, reply_queue)
        
        request = await websocket.recv()
        await websocket.send('200')
        request_json = json.loads(request)
        data = request_json.get('data')
        if data:
            if data.get('type') == 'task':
                await listener.redis_list_returner(data.get('user_id'))
            if data.get('type') == 'voice':
                await listener.voice_producer(data.get('user_id'), data.get('file_id'))
            if data.get('type') == 'message':
                await listener.redis_list_returner(data.get('user_id'))
            if data.get('type') == 'test':
                await test_queue.put(data.get('message'))
            if data.get('type') == 'reply_message':
                await reply_queue.put((data.get('user_id'), data.get('message')))

        else:
            pass

        await message_queue.join()
        await test_queue.join()
        await voice_queue.join()
        await decode_queue.join()

        """# Cancel our worker tasks.
        for task in tasks:
            task.cancel()
        # Wait until all worker tasks are cancelled.
        await asyncio.gather(*tasks, return_exceptions=True) """


if __name__ == '__main__':

    if DEBUG:
        host = 'localhost'
        port = 8765
    else:
        host = '0.0.0.0'
        port = os.environ.get('PORT')

    listener = AsyncTelegramListener()

    start_server = websockets.serve(main, host = host, port = port)
    asyncio.get_event_loop().run_until_complete(asyncio.gather(listener.redis_connection_listener(5), start_server))
    asyncio.get_event_loop().run_forever()
