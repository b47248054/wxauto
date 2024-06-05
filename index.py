
from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from haper.order import OrderDataHandler

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'super-secret'  # 设置JWT密钥
jwt = JWTManager(app)

# Mock user data
users = {
    'user123': 'pass123321'
}

@app.route('/', methods=['GET'])
def default_index():
    return app.send_static_file('index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if data['username'] == 'user123' and data['password'] == 'pass123321':
        access_token = create_access_token(identity=data['username'])
        # return jsonify(access_token=access_token), 200
        return jsonify({'success': True, 'message': '登录成功', 'access_token': access_token}), 200
    else:
        return jsonify({'message': '用户名或密码错误'}), 401

@app.route('/order_list', methods=['GET'])
def order_list():
    return app.send_static_file('order_list.html')

# @app.route('/add_order', methods=['POST'])
# def add_order():
#     order_data_handler = OrderDataHandler()
#     order_data = request.get_json()
#     new_order = OrderInfo(**order_data)
#     order_data_handler.add_order(new_order)
#     return jsonify({'success': True, 'message': '订单添加成功'}), 200

@app.route('/order_data', methods=['POST'])
@jwt_required()
def order_data():
    order_data_handler = OrderDataHandler()
    orders_data = order_data_handler.get_order_data()
    return jsonify({'success': True, 'message': '请求成功', 'orders_data': orders_data}), 200

@app.errorhandler(404)
def not_found(error):
    return 'Not Found', 404


if __name__ == '__main__':
    app.run(debug=True, port=80)
