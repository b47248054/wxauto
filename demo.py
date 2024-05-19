import time

from wxauto import WeChat

wx = WeChat()
sessiondict=wx.GetSessionList(reset=True,newmessage=True)
print(sessiondict)
#
# # 获取当前聊天页面（文件传输助手）消息，并自动保存聊天图片
# msgs = wx.GetAllMessage(savepic=True)
# for msg in msgs:
#     print(f"{msg[0]}: {msg[1]}")
# wechat_id = '13216126002', 'wh12140180360','忠旭2'
# wechat_id = '152'
# 添加客户微信好友
# if len(wx.GetAllFriends(wechat_id)) > 0:
#     print('已添加好友')
# else:
# res = wx.AddFriend(wechat_id,'你好，我是橙心简历助手','忠旭2','打')
# print(res)
# chat = wx.CreateGroup(['简历制作王老师','忠旭2'],'测试群')
#
# chat.SendKeys('亲爱的客户，您好，感谢您对我们家的信任在我们家下单，我是店铺负责人，已经帮您分配好执笔老师，简历定制包含个人隐私，在未经本人同意的'
#            '情况下，我们是绝对禁止外发出去，您可放心。')
# chat.SendKeys('{Enter}')
# chat.SendKeys('【客户须知】\n1.简历一般初稿时间在客户提供了相关资料信息后6-24小时左右，如需加急得先联系平台在线客服；\n2.模板确认好以后，中途不'
#            '可更换；\n3.简历在定稿以后会发word和pdf 2个电子版文件，pdf版是可以直接微信发给对方HR或者邮箱上传，word版是后期可以再修改， 亲'
#            '要妥善存储；\n4.定稿后 30 天内免费售后噢（不包括更换模板、求职意向变动带来的内容改动）；\n5.为了保障服务质量，我们采用建群方式沟'
#            '通，亲不要私加执笔老师，有任何问题可以在本群直接沟通即可；\n6.切记不要跟执笔老师私下交易，私下交易，出现任何问题，本店概不负责。')
# chat.SendKeys('{Enter}')
# chat.SendKeys('【注意】如有老师私加好友或者服务态度问题， 亲可以第一时间向我反馈，我了解情况后会第一时间为您解决问题。请勿添加写手的私人微信！若'
#            '写手私自添加您的微信，欢迎举报，核实属实，简历制作免费，感谢信任和支持!')
# chat.SendKeys('{Enter}')

# 发送消息
# who = '文件传输助手'
# for i in range(3):
#     wx.SendMsg(f'wxauto测试{i+1}', who)
# 客服组
# sales = ['忠旭','忠旭2','王明雪']
# # 监听客服微信消息
# for sale in sales:
#     wx.AddListenChat(who=sale)  # 添加监听对象
#     print(f'开始监听微信消息:{sale}')
#
# # 持续监听消息
# wait = 10  # 设置1秒查看一次是否有新消息
# while True:
#     msgs = wx.GetListenMessage()
#     for chat in msgs:
#         msg = msgs.get(chat)   # 获取消息内容
#         for i in msg:
#             if i.type == 'friend':
#                 # ===================================================
#                 # 处理消息逻辑
#                 print(f'收到好友消息:{i.info}')
#                 reply = '收到消息，回复中...'
#
#                 # ===================================================
#
#                 # 回复消息,会阻断其他操作
#                 chat.SendMsg(reply)  # 回复
#     time.sleep(wait)
