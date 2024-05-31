import sqlite3
from datetime import datetime

from haper.config import Config


class CommandMessage:

    type = 'command'

    def __init__(self, command: int, sender, content, message_id, chat):
        self.sender = sender
        self.sender_type = self.get_sender_type(sender)
        self.content = content
        self.message_id = message_id
        self.chat = chat
        self.command = self.parse_command(command)

    def parse_command(self, command: int):
        if command:
            return command
        # 解析命令，提取引用的内容
        if self.content.startswith('1\n引用') or self.content.startswith('2\n引用') or self.content.startswith('3\n引用') or self.content.startswith('4\n引用') or self.content.startswith('5\n引用'):
            return int(self.content.split('\n', 1)[0])
        else:
            return None

    def get_sender_type(self, sender_id):
        if sender_id in Config.customer_service_ids:
            return '客服'
        elif sender_id in Config.writer_ids.keys():
            return '写手'
        elif sender_id in Config.system_ids:
            return '系统'
        else:
            return None

    def is_history_message(self):
        mdh = MessageDataHandler()
        message = mdh.get_message_by_id(self.message_id)
        if message:
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

    def get_message_by_id(self, message_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM receive_msgs WHERE message_id =?
            ''', (message_id,))
            row = cursor.fetchone()
            if row:
                return CommandMessage(row[1], row[2], row[3], row[4], row[5])
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
                messages.append(CommandMessage(row[1], row[2], row[3], row[4], row[5]))
            return messages