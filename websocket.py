import asyncio
import websockets
import aioredis
import os
import json
import aiohttp
import random
import datetime
import functools
import speech_recognition as sr
from threading import Thread
import time
from decoder import TextDecoder
import re


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
        self.session = aiohttp.ClientSession()
        self.TOKEN = os.environ.get('REMINDME_TOKEN')
        self.URL = f'https://api.telegram.org/bot{self.TOKEN}'
        self.SEND_MESSAGE_URL = os.path.join(self.URL, 'sendMessage')
        self.MESSAGE_DELAY = 300 ### 5 minutes
        self.SEND_MESSAGE_INTERVAL = 120 ### 2 minutes before and after
        self.REDIS_TOKEN = os.environ.get('REDIS_TOKEN')
        self.voice_queue = asyncio.Queue()
        self.message_queue = asyncio.Queue()
        self.decode_queue = asyncio.Queue()
        self.start_converters()
    

    def start_converters(self):
        for i in range(5):
            loop = asyncio.get_event_loop()
            task = loop.create_task(self.voice_converter(self.voice_queue))
            decode_task = loop.create_task(self.text_decoder(self.decode_queue))
            message_task = loop.create_task(self.message_sender(self.message_queue))

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

    async def text_decoder(self, queue):
        while True:
            message, user_id = await queue.get()
            decoder = TextDecoder(message).check_text()
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
    
    async def redis_connection_listener(self, request_interval):

        redis = await aioredis.create_redis_pool(self.REDIS_TOKEN, encoding="utf-8")
        while True:
            print('Connecting to Redis database')
            users = await redis.smembers('users')
            for user in users:
                first_task_before = await redis.zrange(user, 0, 0)
                closest_task = await redis.zpopmin(user)
                first_task_after = await redis.zrange(user, 0, 0)
                print(closest_task, '-----', first_task_before, '-------', first_task_after)
                if closest_task:
                    time_delta =  int(closest_task[1]) - int(datetime.datetime.now().timestamp())
                    if abs(time_delta) < self.SEND_MESSAGE_INTERVAL:
                        print('Send message to user', user)
                        message_to_send = f'You asked us to remind you about: {closest_task[0][11:]}'
                        try:
                            async with self.session.post(self.SEND_MESSAGE_URL, data= {'chat_id': user, 'text': message_to_send}) as response:
                                print(response.status)
                                if response.status == 200:
                                    print('Success')
                                else:
                                    print(f'Message for user {user} was delayed')
                                    delay = int(closest_task[1]) + self.MESSAGE_DELAY
                                    await redis.zadd(user, delay, closest_task[0])
                        except Exception as e:
                            print(e)
                    elif time_delta < -200:
                        print('Delte unsend message. Time expired')
                    else:
                        print('Adding task back', int(closest_task[1]), closest_task[0])
                        await redis.zadd(user, int(closest_task[1]), closest_task[0])

            await asyncio.sleep(request_interval)

        redis.close()
        await redis.wait_closed()

    async def redis_manager(self, user_id, time, task):

        redis = await aioredis.create_redis_pool(self.REDIS_TOKEN)
        await redis.sadd('users', user_id)
        await redis.zadd(str(user_id), int(time), f'{int(time)}.{task}')
        redis.close()
        await redis.wait_closed()

    
    async def redis_list_returner(self, user_id):

        redis = await aioredis.create_redis_pool(self.REDIS_TOKEN, encoding="utf-8")
        task_list = await redis.zrange(user_id, 0, -1)
        if task_list:
            task_list = [(task.split('.')) for task in task_list]
            return_task_list = [(datetime.datetime.fromtimestamp(int(task[0])).strftime('%d.%m.%y %H:%M'), task[1]) for task in task_list]
            reply_message = ''
            for index, task in enumerate(task_list):
                task_time = datetime.datetime.fromtimestamp(int(task[0])).strftime('%d.%m.%y %H:%M')
                reply_message += f'{index+1}) {task_time} ----> {task[1]}\n'
            await self.message_queue.put((reply_message, user_id))
        else:
            await self.message_queue.put(('В списке заданий покати шаром', user_id))
        redis.close()
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
            #print(f'Started download link {download_link} {datetime.datetime.now()}')
            time = datetime.datetime.now().strftime('%d_%m_%y_%H_%M_%S')
            proc = await asyncio.create_subprocess_shell(
                f'ffmpeg -i {download_link} -f wav -',
                stdout=asyncio.subprocess.PIPE
                )
            stdout, stderr = await proc.communicate()
            thread = SpeechRecognitionThread(stdout, self.message_queue, self.decode_queue, user_id)
            thread.start()
            voice_queue.task_done()
            #print(f'Ended download link {download_link} {datetime.datetime.now()}')

    
async def main(websocket, path, listener, message_queue):
        
        request = await websocket.recv()
        request_json = json.loads(request)
        data = request_json.get('data')
        if data:
            if data.get('type') == 'task':
                await listener.redis_list_returner(data.get('user_id'))
            if data.get('type') == 'voice':
                await listener.voice_producer(data.get('user_id'), data.get('file_id'))
            if data.get('type') == 'message':
                await listener.redis_list_returner(data.get('user_id'))

        else:
            pass

        await websocket.send('200')


if __name__ == '__main__':

    message_queue = asyncio.Queue()

    listener = AsyncTelegramListener()
    start_server = websockets.serve(functools.partial(main, listener=listener, message_queue = message_queue), "0.0.0.0", os.environ.get('PORT'))
    
    asyncio.get_event_loop().run_until_complete(asyncio.gather(listener.redis_connection_listener(5), start_server))
    asyncio.get_event_loop().run_forever()

