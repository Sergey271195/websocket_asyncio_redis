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

    def __init__(self, text):
        self.text = text.lower()

    def check_text(self):

        if self.text.startswith('список'):
            list_date_expression = re.compile(r'список ((?P<today>сегодня)|(?P<tomorrow>завтра)|(?P<day>\b\d{1,2}\b)\s?(?P<month>\w+))')
            date_match = re.search(list_date_expression, self.text)
            return('list')

        else:
            test_expression = re.compile(r'(((?P<today>сегодня)|(?P<tomorrow>завтра)|(?P<day>\b\d{1,2}\b)\s?(?P<month>\w+))\s)?(в\s)?(?P<hour>\d{1,4})(?P<minutes>:\d{2})?\s(?P<task>.*)')
            test_match = re.search(test_expression, self.text)

            if test_match:
                today = test_match.group('today')
                tomorrow = test_match.group('tomorrow')
                day = test_match.group('day')
                month = test_match.group('month')
                hour = test_match.group('hour')
                minutes = test_match.group('minutes')
                task = test_match.group('task')

                if tomorrow:
                    add_day = datetime.datetime.now().day + 1
                    add_month = datetime.datetime.now().month
                    add_year = datetime.datetime.now().year
                
                elif day:
                    add_day = int(day)
                    add_year = datetime.datetime.now().year
                    if month in MONTH_DICT.keys():
                        add_month = MONTH_DICT[month]


                else:
                    add_day = datetime.datetime.now().day
                    add_month = datetime.datetime.now().month
                    add_year = datetime.datetime.now().year

                if hour:
                    if not minutes:
                        if len(hour) < 3:
                            add_minutes = 0
                            add_hour = int(hour)
                        elif len(hour) == 3:
                            add_hour = int(hour[:1])
                            add_minutes = int(hour[1:])
                        elif len(hour) == 4:
                            add_hour = int(hour[:2])
                            add_minutes = int(hour[2:])
                    else:
                        add_hour = int(hour)
                        add_minutes = int(minutes[1:])


                

                if not all([add_day, add_month, add_year, task]) and add_hour != None:
                    print('Something is missing')

                else:
                    try:
                        return_date = datetime.datetime(add_year, add_month, add_day, add_hour, add_minutes)
                        return_task = task
                        return((return_date, return_task))
                    except Exception as e:
                        print(e)
            
            else:
                print('Wrong input')

