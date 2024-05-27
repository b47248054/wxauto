import time

from haper.config import Haperlog, CommandMessage


class Order:
    def __init__(self, info, wechat_id, order_id):
        self.info = info  # 订单消息，去除【微信】，用于发给写手
        self.wechat_id = wechat_id  # 微信ID
        self.order_id = order_id  # 订单ID
        self.worker = None  # 订单分配的写手
        self.create_time = round(time.time())  # 订单创建时间
        self.finish_time = None  # 订单完成时间
        self.status = {
            'customer_added': False,  # 客户是否已添加
            'worker_assigned': False,  # 订单是否已分配给写手
            'work_group_created': False,  # 群是否已创建
        }

    def set_info(self, info):
        self.info = info

    def set_wechat_id(self, wechat_id):
        self.wechat_id = wechat_id
        self.status['customer_added'] = False

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

class OrderListener:
    def __init__(self,queue):
        self.queue = queue
        self.order_info = {}  # 初始化为空的 order_info
        self.sent_messages = set()  # 用集合来记录已发送的消息的唯一标识

    def add(self, command_message, order):
        # command_message = CommandMessage(command=None, sender=i.sender, content=i.content, message_id=i.message_id, wechat=chat)
        # command_message = CommandMessage(None, i.sender, i.content, i.id, chat)
        self.order_info[order.order_id] = {
            'command_message': command_message,
            'order': order,
            'sender_id': 'SYS',
            'message': command_message.content,
            'chat': command_message.chat,
            'add_customer': {'silence_time': 600, 'last_action_time': order.create_time, 'time_interval': 300, 'executed_times': 0, 'max_execution_times': 2},
            'assign_worker': {'silence_time': 600, 'last_action_time': order.create_time, 'time_interval': 300, 'executed_times': 0, 'max_execution_times': 2},
            'notified': {'add_customer': False, 'assign_worker': False}
        }
        Haperlog.logger.debug(f'Added to OrderListener : {self.order_info[order.order_id]}.')

    def listen_and_forward(self):
        wait = 15  # 设置15秒查看一次
        while True:
            time.sleep(wait)
            for order_id, order_info in self.order_info.items():
                Haperlog.logger.debug(f'---Checking order start: {order_info['order']} .')
                try:
                    # 判断好友申请是否通过，每15秒检查一次
                    self.check_and_dispatch_message(order_info, order_id, 1, 'customer_added', 'only_check')

                    # 订单是否有写手接单，如果超过静默时间，则派单，每300秒派一次
                    self.check_and_dispatch_message(order_info, order_id, 2, 'worker_assigned', 'assign_worker')

                    # 订单是否已经拉群
                    self.check_and_dispatch_message(order_info, order_id, 3, 'work_group_created', 'create_group')

                    # 判断是否添加好友，如果未添加，每300秒重新添加一次
                    self.check_and_dispatch_message(order_info, order_id, 4, 'customer_added', 'add_customer')

                    self.check_and_notify(order_info, 'add_customer')
                    self.check_and_notify(order_info, 'assign_worker')

                except Exception as e:
                    Haperlog.logger.exception(f'---Error occurred while checking order: {order_info["order"]} . Error: {e}', {e})

                Haperlog.logger.debug(f'---Checking order end: {order_info["order"]} .')

    # 判断消息发送次数，如果超过最大测试则通知客服
    def check_and_notify(self, order_info, action_type):
        if action_type == 'add_customer' or action_type == 'assign_worker':
            if order_info['notified'][action_type] is False and order_info[action_type]['executed_times'] >= order_info[action_type]['max_execution_times']:
                current_time = round(time.time())
                last_action_time = order_info[action_type]['last_action_time']
                time_interval = order_info[action_type]['time_interval']
                # 计算距离上次执行操作的时间间隔
                time_since_last_action = current_time - last_action_time
                if time_since_last_action >= time_interval:
                    # 发送通知消息
                    command_message = CommandMessage(5, order_info['sender_id'], self.transfer_message(order_info['message'], 5), order_info['command_message'].message_id, order_info['chat'])
                    self.queue.put(command_message)
                    Haperlog.logger.debug(f'---Notified message[{order_info["order"].order_id}] : {command_message}')
                    order_info['notified'][action_type] = True  # 通知已发送

    def check_and_dispatch_message(self, order_info, order_id, command, status_key, action_type):
        if order_info['order'].status[status_key] is False and self.exists_message(order_id, command) is False and self.check_if_action_needed(order_info, action_type):
            command_message = CommandMessage(command, order_info['sender_id'], self.transfer_message(order_info['message'], command), order_info['command_message'].message_id, order_info['chat'])
            self.queue.put(command_message)
            message_id = (order_id, command)
            self.sent_messages.add(message_id)
            Haperlog.logger.debug(f'---Dispatching message[{message_id}] : {command_message}')

    def check_if_action_needed(self, order_info, action_type):
        current_time = round(time.time())

        if action_type == 'only_check':
            return True  # 时间不用判断，直接返回True

        if action_type == 'create_group':
            if order_info['order'].status['customer_added'] is True and order_info['order'].status['worker_assigned'] is True:
                return True  # 客户已添加，写手已分配，需要创建群

        if action_type == 'add_customer' or action_type == 'assign_worker':
            silence_time = order_info[action_type]['silence_time']
            last_action_time = order_info[action_type]['last_action_time']
            time_interval = order_info[action_type]['time_interval']
            executed_times = order_info[action_type]['executed_times']
            max_execution_times = order_info[action_type]['max_execution_times']  # 最大执行次数

            # 如果订单创建后不足首次静默时间，则不执行任何操作
            if current_time - order_info['order'].create_time < silence_time:
                return False

            # 判断是否超过最大执行次数
            if executed_times >= max_execution_times:
                return False

            # 计算距离上次执行操作的时间间隔
            time_since_last_action = current_time - last_action_time
            if time_since_last_action >= time_interval:
                # 更新上次操作时间
                order_info[action_type]['last_action_time'] = current_time
                # 更新执行次数
                order_info[action_type]['executed_times'] += 1
                return True
        return False

    def get_order(self, order_id):
        # 从order_list中获取订单信息
        if order_id not in self.order_info:
            return None
        # 如果存在则返回订单信息
        return self.order_info[order_id]['order']

    # 构造系统消息，设定command类型为 1，好友申请是否通过，4，加好友，2，派单，3，拉群
    def transfer_message(self, message, command):
        message = f'{command}\n{message.split('\n', 1)[1]}'
        return message

    def exists_message(self, order_id, command):
        # 使用订单编号和命令类型的元组作为唯一标识
        message_id = (order_id, command)
        if message_id in self.sent_messages:
            return True  # 如果消息已经存在，则不再发送
        else:
            return False

    def consume_message(self, order_id, command):
        # 处理消费成功的消息，并重置状态，需要重新发送
        message_id = (order_id, command)
        if message_id in self.sent_messages:
            self.sent_messages.remove(message_id)  # 重置消息为未发送状态
            Haperlog.logger.debug(f'---Consumed message[{message_id}]')