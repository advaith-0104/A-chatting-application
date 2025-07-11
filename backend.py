import json
import os
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sys
import firebase_admin
from firebase_admin import credentials, firestore, auth

# Firebase Initialization
FIREBASE_SERVICE_ACCOUNT_KEY_CONTENT = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY_CONTENT')

if not FIREBASE_SERVICE_ACCOUNT_KEY_CONTENT:
    print("Error: FIREBASE_SERVICE_ACCOUNT_KEY_CONTENT environment variable not set.")
else:
    try:
        cred = credentials.Certificate(json.loads(FIREBASE_SERVICE_ACCOUNT_KEY_CONTENT))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firebase Admin SDK initialized successfully.")
    except Exception as e:
        print(f"Error initializing Firebase Admin SDK: {e}")
        print("Please ensure FIREBASE_SERVICE_ACCOUNT_KEY_CONTENT is valid JSON.")

# Helper function to convert Firestore Timestamp objects to datetime objects using duck typing
def convert_firestore_timestamp(obj):
    # Check if the object has an 'isoformat' method, which Timestamp objects do
    if hasattr(obj, 'isoformat') and callable(getattr(obj, 'isoformat')):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: convert_firestore_timestamp(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_firestore_timestamp(elem) for elem in obj]
    return obj

# Flask Application Setup
app = Flask(__name__)
CORS(app)

# API Endpoints
@app.route('/')
def serve_index():
    return send_from_directory(os.getcwd(), 'index.html')

@app.route('/<path:path>')
def serve_static_files(path):
    return send_from_directory(os.getcwd(), path)

@app.route('/register', methods=['POST'])
def register_user():
    data = request.json
    email = data.get('email')
    username = data.get('username')
    password = data.get('password')
    confirm_password = data.get('confirm_password')

    if not all([email, username, password, confirm_password]):
        return jsonify({"message": "All fields are required!"}), 400

    if password != confirm_password:
        return jsonify({"message": "PASSWORDS DO NOT MATCH!!! TRY AGAIN"}), 400

    if len(password) < 6:
        return jsonify({"message": "Password must be at least 6 characters long."}), 400

    try:
        users_ref = db.collection('users')
        username_query = users_ref.where('username', '==', username).limit(1).get()
        if len(username_query) > 0:
            return jsonify({"message": "Username already taken."}), 409

        user_record = auth.create_user(email=email, password=password)
        user_id = user_record.uid

        user_data = {
            "email": email,
            "username": username,
            "password_for_backend_check": password,
            "friends": []
        }
        db.collection('users').document(user_id).set(user_data)

        print(f"Registered new user: {username} ({email}) with UID: {user_id}")
        return jsonify({"message": "Registration successful! You can now log in."}), 201

    except firebase_admin.auth.EmailAlreadyExistsError:
        return jsonify({"message": "Email already registered."}), 409
    except Exception as e:
        print(f"Error during registration: {e}")
        return jsonify({"message": f"An error occurred during registration: {e}"}), 500

@app.route('/login', methods=['POST'])
def login_user():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not all([email, password]):
        return jsonify({"message": "Email and password are required!"}), 400

    try:
        users_ref = db.collection('users')
        user_query = users_ref.where('email', '==', email).limit(1).get()

        if not user_query:
            return jsonify({"message": "Invalid email or password."}), 401

        user_doc = user_query[0]
        user_data = user_doc.to_dict()
        user_id = user_doc.id

        if user_data.get('password_for_backend_check') != password:
            return jsonify({"message": "Invalid email or password."}), 401

        print(f"User logged in: {user_data['username']} (UID: {user_id})")
        return jsonify({
            "message": "Login successful!",
            "user_id": user_id,
            "username": user_data['username']
        }), 200

    except Exception as e:
        print(f"Error during login: {e}")
        return jsonify({"message": "An error occurred during login. Please try again."}), 500

@app.route('/users/<user_id>', methods=['GET'])
def get_all_users(user_id):
    users_list = []
    try:
        users_ref = db.collection('users')
        users = users_ref.stream()

        for user_doc in users:
            user_data = user_doc.to_dict()
            if user_doc.id != user_id:
                users_list.append({
                    "id": user_doc.id,
                    "username": user_data['username']
                })
        return jsonify({"users": users_list}), 200
    except Exception as e:
        print(f"Error getting all users: {e}")
        return jsonify({"message": "Failed to load users."}), 500

@app.route('/friends/<user_id>', methods=['GET'])
def get_friends(user_id):
    try:
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            return jsonify({"message": "User not found."}), 404

        user_data = user_doc.to_dict()
        friend_ids = user_data.get('friends', [])

        friend_usernames = []
        for friend_id in friend_ids:
            friend_info_doc = db.collection('users').document(friend_id).get()
            if friend_info_doc.exists:
                friend_info_data = friend_info_doc.to_dict()
                friend_usernames.append({
                    "id": friend_info_doc.id,
                    "username": friend_info_data['username']
                })
        return jsonify({"friends": friend_usernames}), 200
    except Exception as e:
        print(f"Error getting friends for {user_id}: {e}")
        return jsonify({"message": "Failed to load friends."}), 500

@app.route('/send_friend_request', methods=['POST'])
def send_friend_request():
    data = request.json
    sender_id = data.get('sender_id')
    receiver_id = data.get('receiver_id')

    if not all([sender_id, receiver_id]):
        return jsonify({"message": "Sender and receiver IDs are required."}), 400

    if sender_id == receiver_id:
        return jsonify({"message": "Cannot send friend request to yourself."}), 400

    try:
        sender_doc = db.collection('users').document(sender_id).get()
        receiver_doc = db.collection('users').document(receiver_id).get()

        if not sender_doc.exists or not receiver_doc.exists:
            return jsonify({"message": "Sender or receiver not found."}), 404

        sender_data = sender_doc.to_dict()
        receiver_data = receiver_doc.to_dict()

        if receiver_id in sender_data.get('friends', []):
            return jsonify({"message": f"Already friends with {receiver_data['username']}."}), 409

        existing_outgoing_request_query = db.collection('friend_requests') \
            .where('sender_id', '==', sender_id) \
            .where('receiver_id', '==', receiver_id) \
            .where('status', '==', 'pending') \
            .limit(1).get()
        if len(existing_outgoing_request_query) > 0:
            return jsonify({"message": "Friend request already sent to this user."}), 409

        existing_incoming_request_query = db.collection('friend_requests') \
            .where('sender_id', '==', receiver_id) \
            .where('receiver_id', '==', sender_id) \
            .where('status', '==', 'pending') \
            .limit(1).get()
        if len(existing_incoming_request_query) > 0:
            return jsonify({"message": f"{receiver_data['username']} has already sent you a friend request. Please check your incoming requests."}), 409

        request_data = {
            "sender_id": sender_id,
            "sender_username": sender_data['username'],
            "receiver_id": receiver_id,
            "receiver_username": receiver_data['username'],
            "status": "pending",
            "timestamp": firestore.SERVER_TIMESTAMP
        }
        db.collection('friend_requests').add(request_data)

        print(f"Friend request sent from {sender_data['username']} to {receiver_data['username']}")
        return jsonify({"message": "Friend request sent!"}), 200

    except Exception as e:
        print(f"Error sending friend request: {e}")
        return jsonify({"message": "An error occurred while sending friend request."}), 500

@app.route('/friend_requests/<user_id>', methods=['GET'])
def get_friend_requests(user_id):
    incoming_requests = []
    outgoing_requests = []
    try:
        incoming_query = db.collection('friend_requests').where('receiver_id', '==', user_id).where('status', '==', 'pending').stream()
        for req_doc in incoming_query:
            req_data = req_doc.to_dict()
            incoming_requests.append({
                "request_id": req_doc.id,
                "sender_id": req_data['sender_id'],
                "sender_username": req_data['sender_username'],
                "timestamp": convert_firestore_timestamp(req_data['timestamp'])
            })

        outgoing_query = db.collection('friend_requests').where('sender_id', '==', user_id).where('status', '==', 'pending').stream()
        for req_doc in outgoing_query:
            req_data = req_doc.to_dict()
            outgoing_requests.append({
                "request_id": req_doc.id,
                "receiver_id": req_data['receiver_id'],
                "receiver_username": req_data['receiver_username'],
                "timestamp": convert_firestore_timestamp(req_data['timestamp'])
            })

        return jsonify({
            "requests": incoming_requests,
            "outgoing": outgoing_requests
        }), 200
    except Exception as e:
        print(f"Error getting friend requests for {user_id}: {e}")
        return jsonify({"message": "Failed to load friend requests."}), 500

@app.route('/accept_friend_request', methods=['POST'])
def accept_friend_request():
    data = request.json
    requester_id = data.get('requester_id')
    accepter_id = data.get('accepter_id')

    if not all([requester_id, accepter_id]):
        return jsonify({"message": "Requester ID and accepter ID are required."}), 400

    if requester_id == accepter_id:
        return jsonify({"message": "Cannot accept request from yourself."}), 400

    try:
        request_query = db.collection('friend_requests') \
            .where('sender_id', '==', requester_id) \
            .where('receiver_id', '==', accepter_id) \
            .where('status', '==', 'pending') \
            .limit(1).get()

        if not request_query:
            return jsonify({"message": "Pending friend request not found."}), 404

        request_doc = request_query[0]
        request_doc_ref = request_doc.reference
        request_data = request_doc.to_dict()

        request_doc_ref.update({"status": "accepted", "accepted_at": firestore.SERVER_TIMESTAMP})

        db.collection('users').document(requester_id).update({
            'friends': firestore.ArrayUnion([accepter_id])
        })
        db.collection('users').document(accepter_id).update({
            'friends': firestore.ArrayUnion([requester_id])
        })

        print(f"Friend request accepted between {requester_id} and {accepter_id}.")
        return jsonify({"message": "Friend request accepted!"}), 200

    except Exception as e:
        print(f"Error accepting friend request: {e}")
        return jsonify({"message": "An error occurred while accepting friend request."}), 500

@app.route('/decline_friend_request', methods=['POST'])
def decline_friend_request():
    data = request.json
    requester_id = data.get('requester_id')
    decliner_id = data.get('decliner_id')

    if not all([requester_id, decliner_id]):
        return jsonify({"message": "Requester ID and decliner ID are required."}), 400

    if requester_id == decliner_id:
        return jsonify({"message": "Cannot decline request from yourself."}), 400

    try:
        request_query = db.collection('friend_requests') \
            .where('sender_id', '==', requester_id) \
            .where('receiver_id', '==', decliner_id) \
            .where('status', '==', 'pending') \
            .limit(1).get()

        if not request_query:
            return jsonify({"message": "Pending friend request not found."}), 404

        request_doc = request_query[0]
        request_doc_ref = request_doc.reference
        request_data = request_doc.to_dict()

        request_doc_ref.update({"status": "declined", "declined_at": firestore.SERVER_TIMESTAMP})

        print(f"Friend request declined between {requester_id} and {decliner_id}.")
        return jsonify({"message": "Friend request declined."}), 200

    except Exception as e:
        print(f"Error declining friend request: {e}")
        return jsonify({"message": "An error occurred while declining friend request."}), 500


@app.route('/remove_friend', methods=['POST'])
def remove_friend():
    data = request.json
    user_id = data.get('user_id')
    friend_id = data.get('friend_id')

    try:
        user_ref = db.collection('users').document(user_id)
        friend_ref = db.collection('users').document(friend_id)

        user_doc = user_ref.get()
        friend_doc = friend_ref.get()

        if not user_doc.exists or not friend_doc.exists:
            return jsonify({"message": "User or friend not found."}), 404

        user_data = user_doc.to_dict()
        friend_data = friend_doc.to_dict()

        if friend_id not in user_data.get('friends', []):
            return jsonify({"message": "User is not in your friend list."}), 400

        db.collection('users').document(user_id).update({
            'friends': firestore.ArrayRemove([friend_id])
        })
        db.collection('users').document(friend_id).update({
            'friends': firestore.ArrayRemove([user_id])
        })

        related_requests = db.collection('friend_requests').where(
            firestore.FieldFilter('sender_id', 'in', [user_id, friend_id])
        ).where(
            firestore.FieldFilter('receiver_id', 'in', [user_id, friend_id])
        ).get()

        for req_doc in related_requests:
            req_data = req_doc.to_dict()
            if req_data.get('status') in ['pending', 'accepted']:
                db.collection('friend_requests').document(req_doc.id).update({
                    "status": "cancelled_by_unfriend",
                    "cancelled_at": firestore.SERVER_TIMESTAMP
                })
                print(f"Updated friend request {req_doc.id} status to 'cancelled_by_unfriend' due to unfriend action.")


        print(f"User {user_data['username']} removed {friend_data['username']} from friends.")
        return jsonify({"message": "Friend removed successfully!"}), 200
    except Exception as e:
        print(f"Error removing friend: {e}")
        return jsonify({"message": "An error occurred while removing friend."}), 500


@app.route('/chat_history/<user1_id>/<user2_id>', methods=['GET'])
def get_chat_history(user1_id, user2_id):
    chat_id = '_'.join(sorted([user1_id, user2_id]))
    messages = []
    
    try:
        messages_ref = db.collection('chats').document(chat_id).collection('messages').order_by('timestamp').stream()
        for msg_doc in messages_ref:
            msg_data = msg_doc.to_dict()
            
            msg_data['timestamp'] = convert_firestore_timestamp(msg_data.get('timestamp'))
            
            messages.append(msg_data)
            
        return jsonify(messages), 200
    except Exception as e:
        print(f"Error getting chat history for {chat_id}: {e}")
        return jsonify({"message": "Failed to load chat history."}), 500

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.json
    sender_id = data.get('sender_id')
    receiver_id = data.get('receiver_id')
    message_text = data.get('message')

    if not all([sender_id, receiver_id, message_text]):
        return jsonify({"message": "Sender, receiver, and message are required."}), 400

    try:
        sender_user_doc = db.collection('users').document(sender_id).get()
        receiver_user_doc = db.collection('users').document(receiver_id).get()

        if not sender_user_doc.exists or not receiver_user_doc.exists:
            return jsonify({"message": "Sender or receiver not found."}), 404

        sender_user_data = sender_user_doc.to_dict()
        receiver_user_data = receiver_user_doc.to_dict()

        if receiver_id not in sender_user_data.get('friends', []):
            return jsonify({"message": "You can only chat with your friends. Add them first!"}), 403

        chat_id = '_'.join(sorted([sender_id, receiver_id]))

        new_message = {
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "message": message_text,
            "timestamp": firestore.SERVER_TIMESTAMP
        }

        db.collection('chats').document(chat_id).collection('messages').add(new_message)

        print(f"Message from {sender_user_data['username']} to {receiver_user_data['username']}: {message_text}")
        return jsonify({"message": "Message sent successfully!"}), 201
    except Exception as e:
        print(f"Error sending message: {e}")
        return jsonify({"message": "An error occurred while sending message."}), 500

@app.route('/logout', methods=['POST'])
def logout_user():
    user_id = request.json.get('user_id')
    print(f"User {user_id} requested logout.")
    return jsonify({"message": "Logged out successfully!"}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)
