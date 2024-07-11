from flask import Flask, redirect, request, url_for
import requests
from dotenv import load_dotenv
import os


app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()

client_id =  os.getenv('MIRO_CLIENT_ID')
client_secret = os.getenv('MIRO_CLIENT_SECRET')

# Miro API credentials

redirect_uri = 'http://localhost:5000/callback'
authorization_base_url = 'https://miro.com/oauth/authorize'
token_url = 'https://api.miro.com/v1/oauth/token'

@app.route('/')
def index():
    # Redirect the user to Miro's authorization URL
    authorization_url = (
        f'{authorization_base_url}?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}'
    )
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    # Get the authorization code from the callback request
    authorization_code = request.args.get('code')

    # Exchange the authorization code for an access token
    token_data = {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'client_secret': client_secret,
        'code': authorization_code,
        'redirect_uri': redirect_uri,
    }

    response = requests.post(token_url, data=token_data)
    token_json = response.json()

    # Extract the access token from the response
    access_token = token_json.get('access_token')
    refresh_token = token_json.get('refresh_token')

    # Display the access token (for demonstration purposes)
    return f'Access Token: {access_token}<br>Refresh Token: {refresh_token}'

if __name__ == '__main__':
    app.run(debug=True, port=5000)
