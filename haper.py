

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
        self.status = {
            'customer_added': False,  # 客户是否已添加
            'worker_assigned': False,  # 订单是否已分配给写手
            'work_group_created': False,  # 群是否已创建
        }  # 订单状态【客户已添加】【待接单】【制作中】【已发货】【已完成】

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
        return f'Order({self.order_id}, {self.info}, {self.wechat_id}, {self.worker}, {self.status}, {self.create_time}, {self.finish_time}, {self.timeout})'

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
                    if i.type == 'friend':
                        self.logger.info(f'---Received message{i.info}')
                        self.message_queue.put((i.sender, i, chat))
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
        wait = 5*60  # 设置300秒查看一次
        logger.info('Order listener started')
        while True:
            time.sleep(wait)
            for order_id, order_info in self.order_list.items():
                logger.info(f'Checking order {order_id} status')

                # 判断是否添加好友
                if order_info['order'].status['customer_added'] is False:
                    self.queue.put((order_info['sender_id'], self.transfer_message(order_info['message'],1), order_info['chat']))

                # 订单是否有写手接单
                if order_info['order'].status['worker_assigned'] is False:
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
            elif command == '2': # 仅添加好友，不派单
                add_res = self.add_customer_wechat(order.wechat_id,order.order_id)
                if add_res == '已添加':
                    order.set_customer_added()
                chat.SendMsg(f'{order.order_id}{add_res}')
            elif command == '3': # 仅给写手发消息，不加客户微信
                self.dispatch_order(order)
                chat.SendMsg(f'{order.order_id}已派单，等待写手接单')

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
        friends = self.wx.GetAllFriends(wechat_id)
        if len(friends) > 0:
            self.logger.info(f'Customer {wechat_id} already has friends: {friends}')
            for friend in friends:
                # 如果是老客户，需要更新备注名称
                if friend['remark'] != order_id:
                    self.logger.info(f'老客户，需要更新备注名称。Updating customer {wechat_id}[{friend['remark']}] remark to {order_id}')
                    self.wx.UpdateRemark(friend, order_id)
                self.logger.info(f'新客户，Customer {wechat_id}[{friend['remark']}] already has friend with order_id: {order_id}')
                self.wx.SendMsg(f'您好，我是橙心简历负责人，您的订单已收到，稍等会给你和执笔老师拉群，有问题可以随时联系我。', order_id)
            return '已添加'
        else:
            logger.info(f'Customer {wechat_id} not in friends, adding friend with order_id: {order_id}')
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
        work_group = self.wx.CreateGroup([order_info.worker, order_info.order_id], f'【{order_info.order_id}】定制服务群')
        work_group.SendKeys(f'{order_info.info}')
        work_group.SendKeys('{Enter}')
        work_group.SendKeys('亲爱的客户，您好，感谢您对我们家的信任在我们家下单，我是店铺负责人，已经帮您分配好执笔老师，简历定制包含个人隐私，在未经本人同意的情况下，我们是绝对禁止外发出去，您可放心。')
        work_group.SendKeys('{Enter}')
        work_group.SendKeys('【客户须知】\n1.简历一般初稿时间在客户提供了相关资料信息后6-24小时左右，如需加急得先联系平台在线客服；\n2.模板确认好以后，中途不可更换；\n3.简历在定稿以后会发word和pdf 2个电子版文件，pdf版是可以直接微信发给对方HR或者邮箱上传，word版是后期可以再修改， 亲要妥善存储；\n4.定稿后 30 天内免费售后噢（不包括更换模板、求职意向变动带来的内容改动）；\n5.为了保障服务质量，我们采用建群方式沟通，亲不要私加执笔老师，有任何问题可以在本群直接沟通即可；\n6.切记不要跟执笔老师私下交易，私下交易，出现任何问题，本店概不负责。')
        work_group.SendKeys('{Enter}')
        work_group.SendKeys('【注意】如有老师私加好友或者服务态度问题，亲可以第一时间向我反馈，我了解情况后会第一时间为您解决问题。请勿添加写手的私人微信！若写手私自添加您的微信，欢迎举报，核实属实，简历制作免费，感谢信任和支持!')
        work_group.SendKeys('{Enter}')
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