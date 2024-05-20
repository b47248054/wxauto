

import queue
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import sys
from wxauto import WeChat
import threading

# 创建TimedRotatingFileHandler实例
file_handler = TimedRotatingFileHandler('haper.log', encoding='utf-8', when='midnight', interval=1, backupCount=7)
file_handler.suffix = "%Y-%m-%d"
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(pathname)s:%(lineno)d - %(levelname)s - %(message)s'))


# 创建StreamHandler实例
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(pathname)s:%(lineno)d - %(levelname)s - %(message)s'))

# 创建Logger实例并添加处理器
loggername = 'my_logger'
logger = logging.getLogger(loggername)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

class BlockingQueue:
    def __init__(self, maxsize=0):
        self.queue = queue.Queue(maxsize)

    def put(self, item, block=True, timeout=None):
        self.queue.put(item, block, timeout)

    def take(self, block=True, timeout=None):
        while True:
            try:
                return self.queue.get(block, timeout)
            except queue.Empty:
                if not block:
                    raise
                time.sleep(0.1)

class Order:
    def __init__(self, info, wechat_id, order_id):
        self.info = info  # 订单消息，去除【微信】，用于发给写手
        self.wechat_id = wechat_id  # 微信ID
        self.order_id = order_id  # 订单ID
        self.worker = None  # 订单分配的写手
        self.create_time = time.time()  # 订单创建时间
        self.finish_time = None  # 订单完成时间
        self.timeout = 3600  # 订单超时时间，单位秒
        # 初始化每种操作的上次执行时间为负无穷
        self.last_action_time = {action: -float('inf') for action in ["add_customer", "assign_worker"]}
        # 每种操作对应的时间间隔，单位为秒
        self.time_intervals = {"add_customer": 300, "assign_worker": 180}
        self.status = {
            'customer_added': False,  # 客户是否已添加
            'worker_assigned': False,  # 订单是否已分配给写手
            'work_group_created': False,  # 群是否已创建
        }

    def check_if_action_needed(self, action_type):
        current_time = time.time()
        # 检查传入的操作类型是否在时间间隔字典中，如果距上次执行操作的时间已经超过设定的时间间隔，则需要执行操作
        if action_type in self.time_intervals and current_time - self.last_action_time[action_type] >= self.time_intervals[action_type]:
            # 如果满足执行条件，则更新上次操作时间并返回 True，表示需要执行对应操作
            self.last_action_time[action_type] = current_time
            return True
        else:
            # 如果不满足执行条件，则返回 False，表示不需要执行对应操作
            return False

    def set_worker(self, worker):
        if not self.worker:
            self.worker = worker
            self.status['worker_assigned'] = True
            return True
        else:
            return False


    def set_customer_added(self):
        self.status['customer_added'] = True

    def set_work_group_created(self):
        self.status['work_group_created'] = True

    def get_status(self):
        return self.status

    def __str__(self):
        return f'Order({self.order_id}, {self.worker}, {self.status}, {self.create_time})'

class WechatMessageListener:
    def __init__(self, wechat, queue, customer_service_ids, writer_ids, system_ids):
        self.customer_service_ids = customer_service_ids
        self.writer_ids = writer_ids
        self.system_ids = system_ids
        self.message_queue = queue
        self.logger = logging.getLogger(loggername)

        self.wx = wechat
        for id in self.customer_service_ids + self.writer_ids:
            self.wx.AddListenChat(who=id)
            logger.info('添加聊天监听：{}'.format(id))

    def listen_and_forward(self):
        # 持续监听消息
        wait = 1  # 设置1秒查看一次是否有新消息
        while True:
            # 监听微信消息并将其放入消息队列
            msgs = self.wx.GetListenMessage()
            for chat in msgs:
                msg = msgs.get(chat)   # 获取消息内容
                for i in msg:
                    self.logger.info(f'---Received message{i}')
                    if i.type == 'friend':
                        self.message_queue.put((i.sender, i, chat))
                        self.logger.info(f'---put message{i}')
            time.sleep(wait)

class OrderListener:
    def __init__(self,queue):
        self.queue = queue
        self.order_list = {}
        self.logger = logging.getLogger(loggername)

    def add(self, order, message, chat):
        order_info = {
            'order': order,
            'sender_id': 'SYS',
            'message': message,
            'chat': chat
        }
        self.order_list[order.order_id] = order_info
        self.logger.info(f'Added order: {order}')

    def get_order(self, order_id):
        # 从order_list中获取订单信息
        if order_id not in self.order_list:
            return None
        # 如果存在则返回订单信息
        return self.order_list[order_id]['order']

    def listen_and_forward(self):
        wait = 30  # 设置300秒查看一次
        logger.info('Order listener started')
        while True:
            time.sleep(wait)
            for order_id, order_info in self.order_list.items():
                logger.info(f'Checking order {order_id} status.{order_info}')

                # 判断是否添加好友
                if order_info['order'].status['customer_added'] is False and order_info['order'].check_if_action_needed("add_customer"):
                    self.queue.put((order_info['sender_id'], self.transfer_message(order_info['message'],1), order_info['chat']))

                # 订单是否有写手接单
                if order_info['order'].status['worker_assigned'] is False and order_info['order'].check_if_action_needed("assign_worker"):
                    self.queue.put((order_info['sender_id'], self.transfer_message(order_info['message'],2), order_info['chat']))

                # 订单是否已经拉群
                if order_info['order'].status['work_group_created'] is False and order_info['order'].status['customer_added'] is True and order_info['order'].status['worker_assigned'] is True:
                    self.queue.put((order_info['sender_id'], self.transfer_message(order_info['message'],3), order_info['chat']))

    # 转行message，构造系统消息，设定command类型为1，加好友，2，派单，3，拉群
    def transfer_message(self, message, command):
        message.content = f'{command}\n{message.content.split('\n', 1)[1]}'
        return message



class CommandExecutor:
    def __init__(self, wechat, queue, customer_service_ids, writer_ids, system_ids):
        self.customer_service_ids = customer_service_ids
        self.writer_ids = writer_ids
        self.system_ids = system_ids
        self.message_queue = queue
        self.logger = logging.getLogger(loggername)
        self.wx = wechat

    def process_next_message(self, order_listener):
        while True:
            sender_id, message, chat = self.message_queue.take()
            sender_type = self.get_sender_type(sender_id)
            command = self.parse_command(message)
            if command:
                self.logger.info(f'Processing command from {sender_type}: {command}, order info: {message}')
                self.execute_command(sender_id, command, message, sender_type, chat, order_listener)
            else:
                self.logger.info(f'Invalid command from {sender_type}[{sender_id}]: {message.info}')
            time.sleep(1)

    def get_sender_type(self, sender_id):
        if sender_id in self.customer_service_ids:
            return '客服'
        elif sender_id in self.writer_ids:
            return '写手'
        elif sender_id in self.system_ids:
            return '系统'
        else:
            return None

    def parse_command(self, message):
        # 解析命令，提取引用的内容
        logger.info(f'Parsing command : {message}')
        if message.content.startswith('1\n引用') or message.content.startswith('2\n引用') or message.content.startswith('3\n引用'):
            parts = message.content.split('\n', 1)
            return parts[0]
        else:
            return None

    def parse_order(self, message, sender_type):
        # 解析命令，提取引用的内容
        logger.info(f'Parsing message : {message}')
        order_id = message.content.split('【编号】')[1].split('\n')[0] # 获取订单号
        if order_listener.get_order(order_id):
            order = order_listener.get_order(order_id)
            return order
        else:
            if sender_type == '客服':
                info = message.content.split('的消息 : ')[1].split('【微信】')[0]  # 获取订单消息，去除【微信】，用于发给写手
                wechat_id = message.content.split('【微信】')[1].split('\n')[0] # 获取微信ID，客户id，用于加好友
                order = Order(info, wechat_id, order_id)  # 创建订单对象
                return order
            return None

    def execute_command(self, sender_id, command, message, sender_type, chat, order_listener):
        order = self.parse_order(message, sender_type)
        if sender_type == '客服':
            # 监听订单
            order_listener.add(order, message, chat)
            if command == '1': # 派单，给写手发消息，加客户微信
                self.dispatch_order(order)
                add_res = self.add_customer_wechat(order.wechat_id,order.order_id)
                if add_res == '已添加':
                    order.set_customer_added()
                chat.SendMsg(f'{order.order_id}已派单，等待写手接单，客户微信{add_res}')
            # elif command == '2': # 仅添加好友，不派单
            #     add_res = self.add_customer_wechat(order.wechat_id,order.order_id)
            #     if add_res == '已添加':
            #         order.set_customer_added()
            #     chat.SendMsg(f'{order.order_id}{add_res}')
            # elif command == '3': # 仅给写手发消息，不加客户微信
            #     self.dispatch_order(order)
            #     chat.SendMsg(f'{order.order_id}已派单，等待写手接单')

        elif sender_type == '写手':
            if command == '1':
                if not order:
                    chat.SendMsg(f'{message.content.split("【编号】")[1].split("\n")[0]}已失效，请尝试其他订单')
                elif self.accept_order(sender_id, order):
                    chat.SendMsg(f'{order.order_id}接单成功，请稍等拉群')
                else:
                    chat.SendMsg(f'{order.order_id}已经被抢了，请尝试其他订单')

        elif sender_type == '系统':
            # 系统的命令执行逻辑
            if command == '1': # 监听好友是否添加成功
                logger.info(f'Checking if customer {order} has been added to friends')
                add_res = self.add_customer_wechat(order.wechat_id,order.order_id)
                if add_res == '已添加':
                    order.set_customer_added()
                chat.SendMsg(f'{order.order_id}{add_res}')
            elif command == '2': # 监听订单是否分配给写手
                logger.info(f'Checking if order {order} has been assigned to a writer')
                self.dispatch_order(order)
                chat.SendMsg(f'{order.order_id}还没有写手接单，已重新派单，请关注，并私信写手')
            elif command == '3': # 监听订单是否拉群
                logger.info(f'Checking if order {order} has been created a work group')
                chat.SendMsg(f'{order.order_id}，客户添加成功，写手【{order.worker}】已经接单，正在拉群，请稍等...')
                self.start_working(order)

    # 添加客户微信好友
    def add_customer_wechat(self,wechat_id,order_id):
        # 用订单id查找???
        friends = self.wx.GetAllFriends(order_id)
        if len(friends) > 0:
            self.logger.info(f'Customer {wechat_id} already has friends: {friends}')
            for friend in friends:
                # 如果是老客户，需要更新备注名称，发单是微信名称写原订单编号
                if friend['remark'] != order_id:
                    self.logger.info(f'老客户，需要更新备注名称。Updating customer {wechat_id}[{friend['remark']}] remark to {order_id}')
                    self.wx.UpdateRemark(friend, order_id)
                self.logger.info(f'新客户，Customer {wechat_id}[{friend['remark']}] already has friend with order_id: {order_id}')
                self.wx.SendMsg(f'您好，我是橙心简历负责人，您的订单已收到，稍等会给你和执笔老师拉群，有问题可以随时联系我。', order_id)
            return '已添加'
        else:
            logger.info(f'Customer {wechat_id} not in friends, adding friend with order_id: {order_id}')
            self.wx.AddNewFriend(wechat_id,'您好，我是橙心简历负责人',order_id,'打')
            return self.wx.AddFriend(wechat_id,'您好，我是橙心简历负责人',order_id,'打')
    def dispatch_order(self, order):
        self.logger.info(f'Dispatched order: {order}')
        # 遍历所有写手，发送消息
        for writer_id in self.writer_ids:
            self.wx.SendMsg(f'{order.info}\n老师接单吗？接单请引用订单信息，并回复【1】', writer_id)
    def accept_order(self, writer_id, order_info):
        self.logger.info(f'Accepted order: {order_info}')
        return order_info.set_worker(writer_id)


    def start_working(self, order_info):
        self.logger.info(f'Started working on order: {order_info}')
        # 发送消息给客户，通知客户开始制作
        self.wx.CreateGroup([order_info.worker, order_info.order_id], f'【{order_info.order_id}】定制服务群')

        order_info.set_work_group_created()

# 使用示例
customer_service_ids = ['忠旭']
writer_ids = ['忠旭2']
system_ids = ['SYS']

wx = WeChat()
message_queue = BlockingQueue(1000)
command_executor = CommandExecutor(wx, message_queue, customer_service_ids, writer_ids, system_ids)
wechat_listener = WechatMessageListener(wx, message_queue,customer_service_ids,writer_ids,system_ids)
order_listener = OrderListener(message_queue)

def producer():
    wechat_listener.listen_and_forward()

def consumer():
    command_executor.process_next_message(order_listener)

def system_producer():
    order_listener.listen_and_forward()

t1 = threading.Thread(target=producer)
t2 = threading.Thread(target=consumer)
t3 = threading.Thread(target=system_producer)

t1.start()
t2.start()
t3.start()