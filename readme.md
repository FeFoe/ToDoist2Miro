# ToDoIst2Miro

This project integrates Todoist and Miro, allowing synchronization of tasks and collaborators between the two platforms. 
The integration involves fetching tasks and collaborators from Todoist, storing them in a SQLite database, and syncing the tasks to Miro as cards. Existing cards are constantly updated. Persons assigned to tasks are assigned to the Miro cards as tags. Additionally, it fetches items from a "Done" frame in Miro and marks corresponding tasks as completed in Todoist.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Get Access Code from Miro](#get-access-code-from-miro)
- [License](#license)

## Prerequisites

Before you begin, ensure you have met the following requirements:

- Python 3.6 or later installed on your machine.
- `pip` package manager installed.
- A Todoist account and API token.
- A Miro account, board ID, client_id and secret_id.

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/FeFoe/Todoist2Miro.git
   cd Todoist2Miro
   ```

2. Install the required packages:

   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root directory and add your Todoist and Miro API tokens:

   ```env
   TODOIST_API_TOKEN=your_todoist_api_token
   MIRO_ACCESS_TOKEN=your_miro_access_token
   MIRO_BOARD_ID=your_miro_board_id
   TEAM_PROJECT_ID=your_team_project_id
   MIRO_CLIENT_ID=your_miro_client_id
   MIRO_CLIENT_SECRET=your_miro_client_secret
   ```

## Usage

Run the main script to start the synchronization process:

```bash
python skript.py
```

It is recommended to run this regularly, for example via a cronjob.


## Get Access Code from Miro

To get the access code from Miro, follow these steps:

1. Set up a Flask application to handle the OAuth flow.
2. Run the Flask app, which will redirect you to Miro's authorization page.

    ```bash
    python app.py
    ```
3. Authorize the application, and you will be redirected back with an access code. Open your browser and go to `http://localhost:5000`. You will be redirected to Miro's authorization page. Authorize the application, and you will be redirected back with the access token displayed on the page. Save that to the `.env`-File.

## License

This project is licensed under the [MIT License](LICENSE).
