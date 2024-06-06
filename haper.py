import time

from haper.config import Config, Haperlog, BlockingQueue
from haper.message import CommandMessage
from haper.order import Order, OrderListener
from wxauto import WeChat
import threading


class WechatMessageListener:
    def __init__(self, wechat, queue):
        self.customer_service_ids = Config.customer_service_ids
        self.writer_ids = Config.writer_ids
        self.system_ids = Config.system_ids
        self.message_queue = queue

        self.wx = wechat
        for id in self.customer_service_ids:
            self.wx.AddListenChat(who=id)
            Haperlog.logger.debug('添加客服监听：{}'.format(id))
        for id in self.writer_ids.keys():
            self.wx.AddListenChat(who=id)
            Haperlog.logger.debug('添加写手监听：{}'.format(id))
        for id in Config.writer_group_id:
            self.wx.AddListenChat(who=id)
            Haperlog.logger.debug('添加派单群监听：{}'.format(id))

    def listen_and_forward(self):
        # 持续监听消息
        wait = 1  # 设置1秒查看一次是否有新消息
        while True:
            try:
                # 监听微信消息并将其放入消息队列
                msgs = self.wx.GetListenMessage()
                for chat in msgs:
                    msg = msgs.get(chat)   # 获取消息内容
                    for i in msg:
                        if i.type == 'friend':
                            command_message = CommandMessage(None, i.sender, i.content, i.id, chat)
                            Haperlog.logger.debug(f'---Received message : {command_message}')
                            if command_message.command:
                                # 查询消息是否为历史消息，如果是，则忽略
                                if command_message.is_history_message():
                                    Haperlog.logger.debug(f'---Ignore history message : {command_message}')
                                    continue
                                try:
                                    # 保存消息到数据库
                                    command_message.save_to_db()
                                except Exception as e:
                                    Haperlog.logger.exception(f'---Error listening message: {e}, {e}')

                                Haperlog.logger.debug(f'---Dispatching message : {command_message}')
                                self.message_queue.put(command_message)
            except Exception as e:
                Haperlog.logger.exception(f'---Error listening message: {e}, {e}')
            time.sleep(wait)

class CommandExecutor:
    def __init__(self, wechat, queue):
        self.customer_service_ids = Config.customer_service_ids
        self.writer_ids = Config.writer_ids
        self.system_ids = Config.system_ids
        self.message_queue = queue
        self.wx = wechat

    def process_next_message(self, order_listener):
        while True:
            command_message = self.message_queue.take()
            try:
                Haperlog.logger.debug(f'---Processed message start: {command_message}')
                self.execute_command(command_message, order_listener)
            except Exception as e:
                Haperlog.logger.exception(f'---Error processing message: {command_message}, {e}')
            finally:
                Haperlog.logger.debug(f'---Processed message end: {command_message}')

            time.sleep(1)

    # def save_or_update_order(self, message):
    #     # 解析命令，提取引用的内容
    #     Haperlog.logger.debug(f'|---Parsing order : {message.replace('\n', '')}')
    #     order_id = message.split('【编号】')[1].split('\n')[0] # 获取订单号
    #     order = order_listener.get_order(order_id)
    #     update_detail = {'update': {'info': False, 'wechat_id': False}, 'create': False}
    #     if order: # 更新订单
    #         info = message.split('的消息 : ')[1].split('【微信】')[0]  # 获取订单消息，去除【微信】，用于发给写手
    #         wechat_id = message.split('【微信】')[1].split('\n')[0] # 获取微信ID，客户id，用于加好友
    #         if order.info != info:
    #             order.set_info(info)
    #             update_detail['update']['info'] = True
    #         if order.wechat_id != wechat_id:
    #             order.set_wechat_id(wechat_id)
    #             update_detail['update']['wechat_id'] = True
    #         return order, update_detail
    #     else:
    #         info = message.split('的消息 : ')[1].split('【微信】')[0]  # 获取订单消息，去除【微信】，用于发给写手
    #         wechat_id = message.split('【微信】')[1].split('\n')[0] # 获取微信ID，客户id，用于加好友
    #         order = Order(info, wechat_id, order_id)  # 创建订单对象
    #         update_detail['create'] = True
    #         return order, update_detail
    #
    # def load_order(self, message):
    #     # 解析命令，提取引用的内容
    #     Haperlog.logger.debug(f'|---Loading order : {message.replace('\n', '')}')
    #     order_id = message.split('【编号】')[1].split('\n')[0] # 获取订单号 todo: 如果编号不存在，则自动生成一个
    #     if order_listener.get_order(order_id):
    #         order = order_listener.get_order(order_id)
    #         return order
    #
    #     return None

    def execute_command(self, command_message, order_listener):
        command = command_message.command
        sender = command_message.sender
        sender_type = command_message.sender_type
        message = command_message.content
        chat = command_message.chat

        if sender_type == '客服':
            if command == 1: # 派单，给写手发消息，加客户微信,可重复发单
                # 监听订单
                order = Order(command_message)
                if order_listener.add(command_message=command_message, order=order) is False:
                    chat.SendMsg(f'{order.order_id}，您已经派单过了，请不要重复派单')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}，您已经派单过了，请不要重复派单')
                else:
                    dispatch_count, dispatch_records = self.dispatch_order_group(order)
                    if dispatch_count > 0:
                        chat.SendMsg(f'{order.order_id}已派单给【{dispatch_records}】\n等待写手接单')
                        Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}已派单给【{dispatch_records}】等待写手接单')
                    else:
                        chat.SendMsg(f'{order.order_id}无可用写手，请手动派单！！！')
                        Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}无可用写手，请手动派单！！！')

                    add_res = self.add_customer_wechat(order.wechat_id, order.order_id)
                    if '已存在' == add_res:
                        order.set_customer_added()
                        self.wx.SendMsg(f'您好，我是橙心简历负责人，您的订单已收到，稍等会给你和执笔老师拉群，有问题可以随时联系我。', order.order_id)
                        Haperlog.logger.info(f'|---to {order.order_id} msg : 您好，我是橙心简历负责人，您的订单已收到，稍等会给你和执笔老师拉群，有问题可以随时联系我。')
                    elif '未找到' == add_res:
                        order.set_wechat_id(None)
                        chat.SendMsg(f'{order.order_id}，客户微信【{add_res}】，请手动添加！！！')
                        Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}，客户微信【{add_res}】，请手动添加！！！')
                    else:
                        chat.SendMsg(f'{order.order_id}，客户微信【{add_res}】')
                        Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}，客户微信【{add_res}】')

        elif sender_type == '写手':
            order = order_listener.get_order(command_message)
            if command == 1:
                if not order:
                    chat.SendMsg(f'单子已经发出去了，老师后面有其他单子在给您发')
                    Haperlog.logger.info(f'|---to {chat} msg : 单子已经发出去了，老师后面有其他单子在给您发')
                elif self.accept_order(sender, order):
                    chat.SendMsg(f'{order.order_id}接单成功，请稍等拉群')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}接单成功，请稍等拉群')
                elif order.worker == sender:
                    chat.SendMsg(f'{order.order_id}您已经接过单了，请不要重复接单')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}您已经接过单了，请不要重复接单')
                else:
                    chat.SendMsg(f'{order.order_id}已经发出去了，老师后面有其他单子在给您发')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}已经发出去了，老师后面有其他单子在给您发')

        elif sender_type == '写手群':
            order = order_listener.get_order(command_message)
            if command == 1:
                if not order:
                    chat.SendMsg(f'单子已经发出去了，老师后面有其他单子在给您发', at=sender)
                    Haperlog.logger.info(f'|---to {chat} msg : @{sender}，单子已经发出去了，老师后面有其他单子在给您发')
                elif self.accept_order(sender, order):
                    chat.SendMsg(f'{order.order_id}接单成功，请稍等拉群', at=sender)
                    Haperlog.logger.info(f'|---to {chat} msg : @{sender}，{order.order_id}接单成功，请稍等拉群')
                elif order.worker == sender:
                    chat.SendMsg(f'{order.order_id}您已经接过单了，请不要重复接单', at=sender)
                    Haperlog.logger.info(f'|---to {chat} msg : @{sender}，{order.order_id}您已经接过单了，请不要重复接单')
                else:
                    chat.SendMsg(f'{order.order_id}已经发出去了，老师后面有其他单子在给您发', at=sender)
                    Haperlog.logger.info(f'|---to {chat} msg : @{sender}，{order.order_id}已经发出去了，老师后面有其他单子在给您发')

        elif sender_type == '系统':
            order = order_listener.get_order(command_message)
            # 系统的命令执行逻辑
            if command == 1 and order.status['customer_added'] is False: # 监听好友是否添加成功
                Haperlog.logger.debug(f'|---Checking if customer {order} has been added to friends')
                self.wx.SwitchToChat()
                self.wx.ChatWith('文件传输助手')
                if self.wx.CheckNewMessage():
                    sessiondict=self.wx.GetSessionList(newmessage=True)
                    if order.order_id in sessiondict.keys():
                        order.set_customer_added()
                        self.wx.SendMsg(f'您好，我是橙心简历负责人，您的订单已收到，稍等会给你和执笔老师拉群，有问题可以随时联系我。', order.order_id)
                        Haperlog.logger.info(f'|---to {order.order_id} msg : 您好，我是橙心简历负责人，您的订单已收到，稍等会给你和执笔老师拉群，有问题可以随时联系我。')
                        chat_msg = f'{order.order_id}，客户微信【已添加】'
                        chat.SendMsg(chat_msg)
                        Haperlog.logger.info(f'|---to {chat} msg : {chat_msg}')
                order_listener.consume_message(order.order_id,command)
            elif command == 2 and order.status['worker_assigned'] is False: # 监听订单是否分配给写手
                Haperlog.logger.debug(f'|---Checking if order {order} has been assigned to a writer')
                dispatch_count, dispatch_records = self.dispatch_order(order)
                if dispatch_count > 0:
                    chat.SendMsg(f'{order.order_id}还没有写手接单，已重新派单给【{dispatch_records}】\n请关注，并私信写手.')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}还没有写手接单，已重新派单给【{dispatch_records}】请关注，并私信写手.')
                else:
                    chat.SendMsg(f'{order.order_id}无可用写手，请手动派单！！！')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}无可用写手，请手动派单！！！')

                order_listener.consume_message(order.order_id,command)
            elif command == 3 and order.status['work_group_created'] is False: # 监听订单是否拉群
                Haperlog.logger.debug(f'|---Checking if order {order} has been created a work group')
                chat.SendMsg(f'{order.order_id}，客户添加成功，写手【{order.worker}】已经接单，正在拉群，请稍等...')
                Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}，客户添加成功，写手【{order.worker}】已经接单，正在拉群，请稍等...')
                self.start_working(order)
                order_listener.consume_message(order.order_id,command)

            elif command == 4 and order.status['customer_added'] is False and order.wechat_id is not None: # 需要重新添加好友
                Haperlog.logger.info(f'|---Checking if customer {order} has been added to friends')
                add_res = self.add_customer_wechat(order.wechat_id,order.order_id)
                if '已存在' == add_res:
                    order.set_customer_added()
                    self.wx.SendMsg(f'您好，我是橙心简历负责人，您的订单已收到，稍等会给你和执笔老师拉群，有问题可以随时联系我。', order.order_id)
                    Haperlog.logger.info(f'|---to {order.order_id} msg : 您好，我是橙心简历负责人，您的订单已收到，稍等会给你和执笔老师拉群，有问题可以随时联系我。')
                elif '未找到' == add_res:
                    order.set_wechat_id(None)
                    chat.SendMsg(f'{order.order_id}，客户微信【{add_res}】，请手动添加！！！')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}，客户微信【{add_res}】，请手动添加！！！')
                else:
                    chat.SendMsg(f'{order.order_id}，重新添加客户微信【{add_res}】，请关注')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}，重新添加客户微信【{add_res}】，请关注')
                order_listener.consume_message(order.order_id,command)
            elif command == 5:
                if order.status['worker_assigned'] is False:
                    chat.SendMsg(f'{order.order_id}，已多次派单，仍然无人接单，请手动派单！！！')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}，已多次派单，仍然无人接单，请手动派单！！！')
                if order.status['customer_added'] is False and order.wechat_id is not None:
                    chat.SendMsg(f'{order.order_id}，已多次添加【微信】{order.wechat_id}，仍然未通过，请尽快联系客户！！！')
                    Haperlog.logger.info(f'|---to {chat} msg : {order.order_id}，已多次添加【微信】{order.wechat_id}，仍然未通过，请尽快联系客户！！！')

    # 添加客户微信好友
    def add_customer_wechat(self,wechat_id,order_id):
        res = self.wx.AddNewFriend(wechat_id,'您好，我是橙心简历负责人',order_id,'打')
        self.wx.SwitchToChat()
        return res

    # 优先在派单群里发单
    def dispatch_order_group(self, order):
        Haperlog.logger.debug(f'|---Dispatched order: {order}')
        # 发单数量
        count = 0
        # 发单记录
        dispatch_records = []
        # 优先在派单群里发单
        for writer_id in Config.writer_group_id:
            self.wx.SendMsg(f'{order.info}\n老师接单吗？接单请引用订单信息，并回复【1】', writer_id)
            Haperlog.logger.info(f'|---to {writer_id} msg : {order.info.replace('\n', '')}\n老师接单吗？接单请引用订单信息，并回复【1】')
            count += 1
            dispatch_records.append(writer_id)
        return count, dispatch_records

    def dispatch_order(self, order):
        Haperlog.logger.debug(f'|---Dispatched order: {order}')
        # 发单数量
        count = 0
        # 发单记录
        dispatch_records = []
        # 已有人接单情况
        if order.status['worker_assigned'] is True:
            self.wx.SendMsg(f'{order.info}\n老师，订单以这个为准。', order.worker)
            Haperlog.logger.info(f'|---to {order.worker} msg : {order.info.replace('\n', '')}\n老师，订单以这个为准。')
            count += 1
            dispatch_records.append(order.worker)
            return count, dispatch_records

        # 无人接单的情况下，给所有写手，发送消息
        for writer_id, value in self.writer_ids.items():
            if value['status'] == '在线':
                count += 1
                dispatch_records.append(writer_id)
                # if update_info:
                #     self.wx.SendMsg(f'{order.info}\n老师接单吗？以这个为准。接单请引用订单信息，并回复【1】', writer_id)
                #     Haperlog.logger.info(f'|---to {writer_id} msg : {order.info.replace('\n', '')}\n老师接单吗？以这个为准。接单请引用订单信息，并回复【1】')
                # else:
                self.wx.SendMsg(f'{order.info}\n老师接单吗？接单请引用订单信息，并回复【1】', writer_id)
                Haperlog.logger.info(f'|---to {writer_id} msg : {order.info.replace('\n', '')}\n老师接单吗？接单请引用订单信息，并回复【1】')

        return count, dispatch_records

    def accept_order(self, writer_id, order_info):
        Haperlog.logger.debug(f'|---Accepted order [{writer_id}]: {order_info}')
        return order_info.set_worker(writer_id)


    def start_working(self, order_info):
        Haperlog.logger.debug(f'Started working on order: {order_info}')
        msgs = ['亲爱的客户，您好，感谢您对我们家的信任在我们家下单，我是店铺负责人，已经帮您分配好执笔老师，简历定制包含个人隐私，在未经本人同意的情况下，我们是绝对禁止外发出去，您可放心。',
                '【客户须知】\n1.简历一般初稿时间在客户提供了相关资料信息后6-24小时左右，如需加急得先联系平台在线客服；\n2.模板确认好以后，中途不可更换；\n3.简历在定稿以后会发word和pdf 2个电子版文件，pdf版是可以直接微信发给对方HR或者邮箱上传，word版是后期可以再修改， 亲要妥善存储；\n4.定稿后 30 天内免费售后噢（不包括更换模板、求职意向变动带来的内容改动）；\n5.为了保障服务质量，我们采用建群方式沟通，亲不要私加执笔老师，有任何问题可以在本群直接沟通即可；\n6.切记不要跟执笔老师私下交易，私下交易，出现任何问题，本店概不负责。',
                '【注意】如有老师私加好友或者服务态度问题，亲可以第一时间向我反馈，我了解情况后会第一时间为您解决问题。请勿添加写手的私人微信！若写手私自添加您的微信，欢迎举报，核实属实，简历制作免费，感谢信任和支持!']
        # 发送消息给客户，通知客户开始制作
        self.wx.CreateWorkGroup([order_info.worker, order_info.order_id], f'【{order_info.order_id}】定制服务群', msgs)

        order_info.set_work_group_created()
        for msg in msgs:
            Haperlog.logger.info(f'|---to 【{order_info.order_id}】定制服务群 msg : {msg}')

wx = WeChat()
message_queue = BlockingQueue()
command_executor = CommandExecutor(wx, message_queue)
wechat_listener = WechatMessageListener(wx, message_queue)
order_listener = OrderListener(message_queue)

def producer():
    wechat_listener.listen_and_forward()

def consumer():
    command_executor.process_next_message(order_listener)

def system_producer():
    order_listener.listen_and_forward()

# t1 = threading.Thread(target=producer)
t2 = threading.Thread(target=consumer)
#t3 = threading.Thread(target=system_producer)

# t1.start()
t2.start()
#t3.start()

if __name__ == '__main__':
    producer()