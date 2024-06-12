import hashlib
import sqlite3
from datetime import datetime

from haper.config import Config


class CommandMessage:

    '''
    command message example:
    【编号】W99988
    【年限】准研究生
    【实付】150
    【价格】150
    【佣金】150
    【交稿时间】2024/5/11 5小时内出
    【专业、应聘岗位】人物形象
    【旺旺】123
    【微信】忠旭123哈哈哈
    【写手】张三
    '''

    type = 'command'

    def __init__(self, command: int, sender, content, message_id, chat):
        self.sender = sender
        self.sender_type = self.get_sender_type(sender, chat)
        self.content = content
        self.json_content = self.parse_content()
        self.message_id = self.generate_message_id(sender, content)
        self.chat = chat
        self.command = self.parse_command(command)
        self.receive_time = int(datetime.now().timestamp())
        self.execute_status = {
            'customer_added': {'status': False, 'added_time': None, 'notified': False, 'silence_time': 600, 'last_action_time': self.receive_time, 'time_interval': 300, 'executed_times': 0, 'max_execution_times': 2},  # 客户是否已添加
            'worker_assigned': {'status': False, 'assigned_time': None, 'notified': False, 'silence_time': 600, 'last_action_time': self.receive_time, 'time_interval': 300, 'executed_times': 0, 'max_execution_times': 2},  # 订单是否已分配给写手
            'work_group_created': {'status': False, 'created_time': None},  # 群是否已创建
            'evaluation': 0,  # 评价
            'refound': 0  # 退款
        }

    def generate_message_id(self, sender, content):
        sender_hash = int(hashlib.sha256(sender.encode()).hexdigest(), 16)
        content_hash = int(hashlib.sha256(content.encode()).hexdigest(), 16)
        message_id = (sender_hash * content_hash) % (2**31 - 1)  # 取模以确保在SQLite整数类型的范围内
        return message_id

    def parse_content(self):
        # 解析消息模板
        fields = {}
        lines = self.content.split('\n')
        for line in lines:
            if '【' in line and '】' in line:
                key_start = line.find('【') + 1
                key_end = line.find('】')
                value = line[key_end+1:].strip()
                key = line[key_start:key_end]
                fields[key] = value

        # 转换为 JSON 对象
        # json_object = json.dumps(fields, ensure_ascii=False, indent=4)
        return fields

    def parse_command(self, command: int):
        if command:
            return command
        # 解析命令，提取引用的内容
        if self.content.startswith('1\n引用') or self.content.startswith('2\n引用') or self.content.startswith('3\n引用') or self.content.startswith('4\n引用') or self.content.startswith('5\n引用'):
            return int(self.content.split('\n', 1)[0])
        else:
            return None

    def get_sender_type(self, sender_id, chat):
        if sender_id in Config.customer_service_ids:
            return '客服'
        elif chat.who in Config.writer_group_id:
            return '写手群'
        elif sender_id in Config.writer_ids.keys():
            return '写手'
        elif sender_id in Config.system_ids:
            return '系统'
        else:
            return None

    def is_history_message(self):
        mdh = MessageDataHandler()
        message = mdh.count_message_by_id(self.message_id)
        if message > 0:
            return True
        else:
            return False

    def save_to_db(self):
        mdh = MessageDataHandler()
        mdh.save_message(self)

    def __str__(self):
        return f"CommandMessage(command={self.command}, sender={self.sender}[{self.sender_type}], content={self.content.replace('\n', '')}, message_id={self.message_id}, chat={self.chat})"

class MessageDataHandler:
    def __init__(self, db_name='../db/haper.db'):
        self.db_name = db_name
        self.create_table()

    def create_table(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS receive_msgs (
                    id           INTEGER       PRIMARY KEY AUTOINCREMENT,
                    message_id   INTEGER,
                    sender_id    VARCHAR (200),
                    sender_type  VARCHAR (30),
                    content      TEXT,
                    receive_time INTEGER
                );
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_id ON receive_msgs (message_id)')

    def save_message(self, message: CommandMessage):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO receive_msgs (message_id, sender_id, sender_type, content, receive_time)
                VALUES (?,?,?,?,?)
            ''', (message.message_id, message.sender, message.sender_type, message.content, int(datetime.now().timestamp())))

    def count_message_by_id(self, message_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM receive_msgs WHERE message_id =?
            ''', (message_id,))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                return 0

    def get_message_by_id(self, message_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM receive_msgs WHERE message_id =?
            ''', (message_id,))
            row = cursor.fetchone()
            if row:
                # (self, command: int, sender, content, message_id, chat):
                return CommandMessage(None, row[2], row[4], row[1], None)
            else:
                return None

    def get_messages_by_sender(self, sender_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM receive_msgs WHERE sender_id =?
            ''', (sender_id,))
            rows = cursor.fetchall()
            messages = []
            for row in rows:
                return CommandMessage(None, row[2], row[4], row[1], None)
            return messages