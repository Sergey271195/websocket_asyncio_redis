import os, sys, io
import time
import re
import datetime


MONTH_DICT = {
    'январь': 1,
    'января': 1,
    'февраль': 2,
    'февраля': 2, 
    'март': 3,
    'марта': 3,    
    'апрель': 4,
    'апреля': 4, 
    'май': 5,
    'мая': 5, 
    'июнь': 6,
    'июня': 6, 
    'июль': 7,
    'июля': 7, 
    'август': 8,
    'августа': 8, 
    'сентябрь': 9,
    'сентября': 9, 
    'октябрь': 10,
    'октября': 10,  
    'ноябрь': 11, 
    'ноября': 11, 
    'декабрь': 12,
    'декабря': 12  
}

class TextDecoder():

    def __init__(self):
        self.now = datetime.datetime.now()

    def date_parser(self, text):
        date_expression = re.compile(r'((?P<today>сегодня)|(?P<tomorrow>завтра)|(?P<day>\b\d{1,2}\b)\s?(?P<month>\w+))')
        date_search = re.search(date_expression, text)
        if date_search:
            if date_search.group('today'):
                return_date = datetime.datetime(self.now.year, self.now.month, self.now.day)
            elif date_search.group('tomorrow'):
                return_date = datetime.datetime(self.now.year, self.now.month, self.now.day+1)
            elif date_search.group('day') and date_search.group('month'):
                month = MONTH_DICT.get(date_search.group('month'))
                if month:
                    return_date = datetime.datetime(self.now.year, int(month), int(date_search.group('day')))
                else:
                    return_date = None

            if return_date:
                return(re.sub(date_search.group(), '', text).strip(), return_date)


    def time_parser(self, text):
        time_expression = re.compile(r'((в\s)?((?P<time_with_sep>\d{1,2}:\d{2})|(?P<time_without_sep>\d{1,4}\s)))')
        time_search = re.search(time_expression, text)

        if time_search:
            
            time_with_sep = time_search.group('time_with_sep')
            time_without_sep = time_search.group('time_without_sep')

            if time_with_sep:
                hour, minutes = time_with_sep.split(':')
                return_time = datetime.timedelta(hours = int(hour), minutes = int(minutes))

            elif time_without_sep:
                if len(time_without_sep) < 3:
                    return_time = datetime.timedelta(hours = int(time_without_sep))
                elif len(time_without_sep) == 3:
                    return_time = datetime.timedelta(hours = int(time_without_sep[0]), minutes = int(time_without_sep[1:3]))
                else:
                    return_time = datetime.timedelta(hours = int(time_without_sep[0:2]), minutes = int(time_without_sep[2:4]))
            
            return(re.sub(time_search.group(), '', text).strip(), return_time)



    def datetime_parse(self, text):
        date_data = self.date_parser(text)
        if date_data:
            parsed_text, date = date_data
            time_data = self.time_parser(parsed_text)
            if time_data:
                task, time = time_data
                final_time = date + time
                return((final_time, task))
            else:
                final_time = date + datetime.timedelta(hours = 12)
                task = parsed_text
                return((final_time, task))
        else:
            time_data = self.time_parser(text)
            if time_data:
                task, time = time_data
                final_time = datetime.datetime(self.now.year, self.now.month, self.now.day) + time
                return((final_time, task))    



    def main_parser(self, text):
        prefix_expression = re.compile(r'(((?P<delete>^удалить)|(?P<alter>^изменить)|(?P<move>^перенести))\s(?P<key>\d+)\s?)|(?P<list>^список)')
        prefix_search = re.search(prefix_expression, text)

        if prefix_search:
            key = prefix_search.group('key')
            if prefix_search.group('list'):
                string_to_parse = re.sub('список', '', text)
                list_date = self.date_parser(string_to_parse)
                if list_date:
                    period_start = list_date[1]
                    period_end = (list_date[1] + datetime.timedelta(days = 1))
                    return({'type':'list', 'period': [int(period_start.timestamp()), int(period_end.timestamp())]})
                else:
                    return({'type':'list', 'period': list_date})
            if key:
                if prefix_search.group('delete'):
                    return({'type' : 'remove', 'key' : key})
                elif prefix_search.group('alter'):
                    new_task = re.sub(prefix_search.group(), '', text)
                    return({'type' : 'alter', 'key' : key, 'task' : new_task})
                elif prefix_search.group('move'):
                    string_to_parse = re.sub(prefix_search.group(), '', text)
                    if self.datetime_parse(string_to_parse):
                        new_datetime = self.datetime_parse(string_to_parse)[0]
                        return({'type' : 'move', 'key' : key, 'time' : int(new_datetime.timestamp())})
        
        else:
            if self.datetime_parse(text):
                time, task = self.datetime_parse(text)
                return({'type' : 'add', 'task' : task, 'time' : time})


if __name__ == '__main__':

    test_text = ['Напомни 2330 приготовить', 'сегодня в 2:00 meeting', '27 ноября 11:00 собрание', 'завтра в 01:00 meeting',
                '18 июня в 10:00 meeting and other stuff', '18:00 and other stuff', 'Something else', '18 ноября собрание',
                'сегодня в 200 sleepy sleep', 'удалить 12', 'изменить 18 new meeting', 'перенести 44 27 ноября 11:00', 'перенести 5 1:00',
                'перенести 44 сегодня 11:00', 'перенести 5 завтра 1:00', 'список', 'список сегодня', 'список завтра', 'список 27 ноября']

    for command in test_text:
        print(TextDecoder().main_parser(command))

