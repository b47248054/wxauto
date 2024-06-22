import json
import sqlite3
import time
from datetime import datetime
from haper.config import Haperlog
from haper.message import CommandMessage


class Order:
    def __init__(self, command_message):
        self.order_id = command_message.json_content.get('编号')
        self.message_id = command_message.message_id

        # 去除特定字段及其所在的行
        fields_to_remove = ["【微信】", "【实付】", "【写手】", "【旺旺】"]

        filtered_message = command_message.content.split('的消息 : ')[1]
        for field in fields_to_remove:
            filtered_message = '\n'.join([line for line in filtered_message.split('\n') if field not in line])

        self.info = filtered_message # 订单消息，去除【微信】【实付】【写手】【旺旺】，用于发给写手
        self.wechat_id = command_message.json_content.get('微信')
        self.worker = command_message.json_content.get('写手')
        self.create_time = round(time.time())  # 订单创建时间
        self.work_time = None  # 开始工作时间
        self.finish_time = None  # 订单完成时间
        self.evaluation = 0 # 5_star, 4_star, 1_star, refund （3图好评 5、好评 3、差评 0、退款 0）
        self.status = {
            'customer_added': False,  # 客户是否已添加
            'worker_assigned': False if not self.worker else True,  # 订单是否已分配给写手
            'work_group_created': False,  # 群是否已创建
        }
        self.command_message_data = command_message.json_content

    # 重新计算订单佣金
    # def recalculate_commission(self):
    #     try:
    #         # 提取结算价格和佣金的字符串
    #         settlement_price_text = self.info.split('【价格】')
    #         commission_text = self.info.split('【佣金】')
    #
    #         # 转换为数字并保留两位小数
    #         if len(settlement_price_text) > 1:
    #             settlement_price_str = settlement_price_text[1].split('\n')[0]
    #             self.settlement_price = round(float(settlement_price_str), 2)
    #             self.commission = round(self.settlement_price * 0.3, 2)
    #         else:
    #             self.settlement_price = None
    #
    #         if len(commission_text) > 1:
    #             commission_str = commission_text[1].split('\n')[0]
    #             self.commission = round(float(commission_str), 2)
    #         else:
    #             self.commission = round(self.settlement_price * 0.3, 2)
    #     except Exception as e:
    #         Haperlog.logger.exception(f'---Error occurred while recalculate_commission order: {self.order_id} . Error: {e}', {e})
    #
    # def set_info(self, info):
    #     self.info = info
    #     self.recalculate_commission()

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
        self.order_info = {}  # manager.dict()  # 初始化为空的 order_info，线程安全
        self.sent_messages = set()  # 用集合来记录已发送的消息的唯一标识

    def add(self, command_message, order):
        # command_message = CommandMessage(command=None, sender=i.sender, content=i.content, message_id=i.message_id, wechat=chat)
        # command_message = CommandMessage(None, i.sender, i.content, i.id, chat)
        # 如果订单已存在，则返回false
        if order.order_id in self.order_info:
            return False

        # 保存订单信息
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
        try:
            order_data_handler = OrderDataHandler()
            order_data_handler.insert_order(order)
        except Exception as e:
            Haperlog.logger.exception(f'---Error occurred while save_or_update_order : {order} . Error: {e}', {e})

        Haperlog.logger.debug(f'Added to OrderListener : {self.order_info[order.order_id]}.')
        return True

    def listen_and_forward(self):
        wait = 15  # 设置15秒查看一次
        while True:
            time.sleep(wait)
            for order_id, order_info in self.order_info.items():
                if order_info['order'].work_time is None:  # 订单未完成，则监听
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

                        # 订单是否已完成
                        self.check_order_status(order_info)

                    except Exception as e:
                        Haperlog.logger.exception(f'---Error occurred while checking order: {order_info["order"]} . Error: {e}', {e})

                    Haperlog.logger.debug(f'---Checking order end: {order_info["order"]} .')

    # 检查订单是否已完成
    def check_order_status(self, order_info):
        # 获取订单状态
        order_status = order_info['order'].get_status()
        # 如果订单已完成，则从order_list中删除该订单
        if all(order_status.values()):
            try:
                order_info['order'].work_time = round(time.time())
                order_data_handler = OrderDataHandler()
                order_data_handler.update_order(order_info['order'])
                Haperlog.logger.debug(f'---Order completed: {order_info["order"]}')
                # del self.order_info[order_info['order'].order_id]
            except Exception as e:
                Haperlog.logger.exception(f'---Error occurred while save_or_update_order : {order_info["order"]} . Error: {e}', {e})

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

        if action_type == 'only_check' and order_info['order'].wechat_id:
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

    def get_order(self, command_message):
        order_id = command_message.json_content.get('编号')
        # 从order_list中获取订单信息
        if order_id not in self.order_info:
            order_data_handler = OrderDataHandler()
            order = order_data_handler.get_order_by_id(order_id, Order(command_message))
            if order:
                self.add(command_message, order)
            return order
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

class OrderDataHandler:
    def __init__(self, db_name='../db/haper.db'):
        self.db_name = db_name
        self.create_table()

    def create_table(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id VARCHAR(50),
                    message_id VARCHAR(50),  
                    worker_id VARCHAR(50),
                    wechat_id VARCHAR(50),
                    info VARCHAR(1000),
                    command_message_data TEXT,
                    create_time INTEGER,
                    work_time INTEGER,  -- 新增字段用于记录开工时间
                    finish_time INTEGER,
                    evaluation INTEGER,
                    customer_added INTEGER,
                    worker_assigned INTEGER,
                    work_group_created INTEGER
                );
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_id ON order_info (order_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_worker_id ON order_info (worker_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_create_time ON order_info (create_time)')

    def insert_order(self, order):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO orders 
                (order_id, message_id, worker_id, wechat_id, info, command_message_data, create_time, work_time, evaluation, customer_added, worker_assigned, work_group_created) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (order.order_id, order.message_id, order.worker, order.wechat_id, order.info, json.dumps(order.command_message_data), order.create_time, order.work_time, order.evaluation, order.status['customer_added'], order.status['worker_assigned'], order.status['work_group_created']))

    def update_order(self, order):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE orders
                SET 
                    message_id = ?,
                    worker_id = ?,
                    wechat_id = ?,
                    info = ?,
                    command_message_data = ?,
                    create_time = ?,
                    work_time = ?,
                    finish_time = ?,
                    evaluation = ?,
                    customer_added = ?,
                    worker_assigned = ?,
                    work_group_created = ?
                WHERE order_id = ?
            ''', (order.message_id, order.worker, order.wechat_id, order.info, json.dumps(order.command_message_data), order.create_time, order.work_time, order.finish_time, order.evaluation, int(order.status['customer_added']), int(order.status['worker_assigned']), int(order.status['work_group_created']), order.order_id))

    def count_by_order_id(self, order_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM orders 
                WHERE order_id = ?
            ''', (order_id,))
            return cursor.fetchone()[0]

    def get_order_by_id(self, order_id, order):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM orders 
                WHERE order_id = ?
            ''', (order_id,))
            row = cursor.fetchone()
            if row:  # 如果查询结果不为空
                order.order_id = row[1]
                order.message_id = row[2]
                order.worker = row[3]
                order.wechat_id = row[4]
                order.info = row[5]
                order.command_message_data = json.loads(row[6]) if row[6] else None
                order.create_time = row[7]
                order.work_time = row[8]
                order.finish_time = row[9]
                order.evaluation = row[10]
                order.status['customer_added'] = bool(row[11])
                order.status['worker_assigned'] = bool(row[12])
                order.status['work_group_created'] = bool(row[13])
                return order
            else:
                return None

    def get_order_data(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM orders ORDER BY id DESC')
            data = cursor.fetchall()
            orders_data = [{
                'order_id': row[1],
                'message_id': row[2],
                'worker_id': row[3],
                'wechat_id': row[4],
                'info': row[5],
                'command_message_data': json.loads(row[6]) if row[6] else None,
                'create_time': datetime.fromtimestamp(row[7]).strftime('%Y-%m-%d %H:%M:%S') if row[7] else None,
                'work_time': datetime.fromtimestamp(row[8]).strftime('%Y-%m-%d %H:%M:%S') if row[8] else None,
                'finish_time': datetime.fromtimestamp(row[9]).strftime('%Y-%m-%d %H:%M:%S') if row[9] else None,
                'evaluation': row[10],
                'customer_added': bool(row[11]),
                'worker_assigned': bool(row[12]),
                'work_group_created': bool(row[13])
            } for row in data]
            return orders_data
