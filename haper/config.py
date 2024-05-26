import logging
import queue
import time
import sys
# from enum import Enum
from logging.handlers import TimedRotatingFileHandler

# class CustomerServiceCommand(Enum):
#     SUBMIT_ORDER = 1
#
# class WriterCommand(Enum):
#     ACCEPT_ORDER = 1
#     REJECT_ORDER = 2
#
# class SystemCommand(Enum):
#     LISTEN_CUSTOMER_PASSED = 1
#     LISTEN_WORKER_ASSIGNED = 2
#     LISTEN_WORKER_GROUP_CREATED = 3
#     LISTEN_CUSTOMER_ADDED = 4

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

    def __str__(self):
        return f"CommandMessage(command={self.command}, sender={self.sender}[{self.sender_type}], content={self.content.replace('\n', '')}, message_id={self.message_id}, chat={self.chat})"

class Config:

    # 客服账号
    customer_service_ids = ['忠旭']
    # 写手账号
    writer_ids = {'【W99999】接单测试群': {'status': '在线'}}
    # 写手接单群
    writer_group_id = '【W99999】接单测试群'
    # 系统账号
    system_ids = ['SYS']
    # 发送话术
    SEND_MESSAGE = {

    }

class Haperlog:
    # 创建TimedRotatingFileHandler实例
    file_handler = TimedRotatingFileHandler('haper.log', encoding='utf-8', when='midnight', interval=1, backupCount=7)
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('[%(levelname)s] %(asctime)s - %(module)s - %(lineno)d - %(message)s'))

    # 创建StreamHandler实例
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(asctime)s - %(module)s - %(lineno)d - %(message)s'))

    # 创建Logger实例并添加处理器
    loggername = 'haper_logger'
    logger = logging.getLogger(loggername)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

class BlockingQueue:
    def __init__(self, maxsize=1000):
        self.queue = queue.Queue(maxsize)

    def put(self, item, block=True, timeout=None):
        self.queue.put(item, block=block, timeout=timeout)

    def take(self, block=True, timeout=None):
        while True:
            try:
                return self.queue.get(block, timeout)
            except queue.Empty:
                if not block:
                    raise
                time.sleep(0.1)

