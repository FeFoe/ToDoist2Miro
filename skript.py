import sqlite3
import os
import json
import hashlib
from todoist_api_python.api import TodoistAPI
from dotenv import load_dotenv
import miro_api
import pandas as pd
from datetime import datetime
import requests

# Load environment variables from .env file
load_dotenv()

# Access the environment variables
miro_access_token = os.getenv('MIRO_ACCESS_TOKEN')
miro_board_id = os.getenv('MIRO_BOARD_ID')
todoist_api_token = os.getenv('TODOIST_API_TOKEN')
todoist_projectid = os.getenv('TEAM_PROJECT_ID')

# SQLite database file
DB_FILE = 'todoist_tasks.db'
COLORS_FILE = 'colors.csv'

def init_db():
    """Initialize the SQLite database."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.executescript('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                content TEXT,
                project_id TEXT,
                due_date TEXT,
                due_datetime TEXT,
                due_string TEXT,
                due_timezone TEXT,
                creator_id TEXT,
                created_at TEXT,
                assignee_id TEXT,
                assigner_id TEXT,
                comment_count INTEGER,
                is_completed INTEGER,
                description TEXT,
                labels TEXT,
                "order" INTEGER,
                priority INTEGER,
                section_id TEXT,
                parent_id TEXT,
                url TEXT,
                duration_amount INTEGER,
                duration_unit TEXT,
                owner TEXT,
                sync_status INTEGER,
                miro_id TEXT,
                assignee_firstname TEXT,
                assignee_hex_color TEXT
            );
            
            CREATE TABLE IF NOT EXISTS collaborators (
                id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT,
                first_name TEXT,
                hex_color TEXT
            );
        ''')

def add_column_if_not_exists(table, column, column_type):
    """Add a column to an existing table if it does not exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [info[1] for info in cursor.fetchall()]
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

def get_existing_ids(table, column):
    """Get existing IDs from a specified table."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(f'SELECT {column} FROM {table}')
        return set(row[0] for row in cursor.fetchall())

def insert_tasks_into_db(tasks):
    """Insert tasks into the SQLite database."""
    existing_task_ids = get_existing_ids('tasks', 'id')
    new_tasks_count = 0

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        for task in tasks:
            if task.id not in existing_task_ids:
                assignee_id = task.assignee_id
                assignee_hex_color = fetch_assignee_hex_color(cursor, assignee_id) if assignee_id else '#ffffff'
                duration_amount, duration_unit = (task.duration.get('amount'), task.duration.get('unit')) if hasattr(task, 'duration') and task.duration else (None, None)
                
                cursor.execute('''
                    INSERT OR IGNORE INTO tasks (
                        id, content, project_id, due_date, due_datetime, due_string, due_timezone,
                        creator_id, created_at, assignee_id, assigner_id, comment_count, is_completed,
                        description, labels, "order", priority, section_id, parent_id, url,
                        duration_amount, duration_unit, owner, sync_status, miro_id, assignee_firstname,
                        assignee_hex_color
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task.id, task.content, task.project_id, 
                    task.due.date if task.due else None,
                    task.due.datetime if task.due else None,
                    task.due.string if task.due else None,
                    task.due.timezone if task.due else None,
                    task.creator_id, task.created_at, assignee_id, 
                    task.assigner_id, task.comment_count, 
                    int(task.is_completed), task.description, 
                    json.dumps(task.labels), task.order, task.priority, 
                    task.section_id, task.parent_id, task.url, 
                    duration_amount, duration_unit,
                    'owner', 0, None, None,
                    assignee_hex_color
                ))
                new_tasks_count += 1
    return new_tasks_count

def insert_collaborators_into_db(collaborators, colors_dict):
    """Insert collaborators into the SQLite database."""
    existing_collaborator_ids = get_existing_ids('collaborators', 'id')
    new_collaborators_count = 0

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        for collaborator in collaborators:
            if collaborator.id not in existing_collaborator_ids:
                first_name = extract_first_name(collaborator.name)
                hex_color = colors_dict.get(int(collaborator.id)) or generate_hex_color(collaborator.name)
                cursor.execute('''
                    INSERT OR IGNORE INTO collaborators (id, name, email, first_name, hex_color)
                    VALUES (?, ?, ?, ?, ?)
                ''', (collaborator.id, collaborator.name, collaborator.email, first_name, hex_color))
                new_collaborators_count += 1
    return new_collaborators_count

def fetch_todoist_tasks(api_token, project_id):
    """Fetch tasks from a specific Todoist project."""
    api = TodoistAPI(api_token)
    try:
        return api.get_tasks(project_id=project_id)
    except Exception as error:
        print(f"Error fetching tasks: {error}")
        return []

def fetch_todoist_collaborators(api_token, project_id):
    """Fetch collaborators from a specific Todoist project."""
    api = TodoistAPI(api_token)
    try:
        return api.get_collaborators(project_id=project_id)
    except Exception as error:
        print(f"Error fetching collaborators: {error}")
        return []

def update_assignee_firstname():
    """Update the first name of the assignee in the tasks table."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE tasks
            SET assignee_firstname = (
                SELECT first_name
                FROM collaborators
                WHERE tasks.assignee_id = collaborators.id
            )
        ''')
        conn.commit()

def fetch_tasks_to_sync():
    """Fetch tasks to sync from the SQLite database."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, content, description, assignee_hex_color, due_date FROM tasks WHERE sync_status = 0')
        return cursor.fetchall()

def sync_tasks_to_miro():
    """Sync tasks to Miro."""
    api = miro_api.MiroApi(miro_access_token)
    tasks = fetch_tasks_to_sync()
    
    max_per_column = 15
    card_width = 300
    card_height = 100
    horizontal_spacing = 10 #Abstand zwischen Spalten
    vertical_spacing = 1 #Abstand zwischen Zeilen
    x_offset = 0
    y_offset = 0
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        for idx, task in enumerate(tasks):
            column_index = idx // max_per_column
            row_index = idx % max_per_column
            x_position = column_index * (card_width + horizontal_spacing) + x_offset
            y_position = row_index * (card_height + vertical_spacing) + y_offset

            due_date_str = task[4]
            if due_date_str:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d")
                due_date_formatted = due_date.isoformat() + 'Z'
            else:
                due_date_formatted = None 
           
            payload = {
                "data": {
                    "description": task[2],
                    "title": task[1],
                    "dueDate": due_date_formatted
                },
                "style": {
                    "cardTheme": task[3]
                },
                "position": {
                    "x": x_position,
                    "y": y_position
                },
                "geometry": {
                    "height": card_height,
                    "width": card_width
                }
            }
            
            headers = {
                'accept': 'application/json',
                'authorization': f'Bearer {miro_access_token}',
                'content-type': 'application/json',
            }
                    
            response = requests.post(f'https://api.miro.com/v2/boards/{miro_board_id}/cards', headers=headers, json=payload)
            response_id = response.json().get('id') if response else None
            cursor.execute('UPDATE tasks SET sync_status = 1 WHERE id = ?', (task[0],))
            cursor.execute('UPDATE tasks SET miro_id = ? WHERE id = ?', (response_id, task[0]))


def extract_first_name(full_name):
    """Extract the first name from a full name."""
    separators = [' ', '.']
    for sep in separators:
        if sep in full_name:
            return full_name.split(sep)[0].capitalize().strip()
    return full_name.capitalize().strip()

def generate_hex_color(name):
    """Generate a hex color code from a string."""
    color_hash = hashlib.md5(name.encode()).hexdigest()
    return '#' + color_hash[:6]

def fetch_assignee_hex_color(cursor, assignee_id):
    """Fetch the hex color of the assignee."""
    cursor.execute('SELECT hex_color FROM collaborators WHERE id = ?', (assignee_id,))
    result = cursor.fetchone()
    return result[0] if result else generate_hex_color("Unknown Assignee")

def load_colors_from_csv(file_path):
    """Load collaborator colors from a CSV file."""
    if os.path.exists(file_path):
        colors_df = pd.read_csv(file_path)
        return dict(zip(colors_df['id'], colors_df['hex']))
    return {}

def fetch_done_frame_items():
    """Fetch items from the 'done' frame in Miro."""
    api = miro_api.MiroApi(miro_access_token)
    items = api.get_items(miro_board_id)

    rahmen_id = next((item.id for item in items.data if hasattr(item.data.actual_instance, 'title') and item.data.actual_instance.title == "Done"), None)

    return api.get_items_within_frame(miro_board_id, rahmen_id) if rahmen_id else []

def complete_todoist_task(task_id):
    """Update a Todoist task."""
    api = TodoistAPI(todoist_api_token)
        # check in db if task is already completed
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT is_completed FROM tasks WHERE id = ?', (task_id,))
        result = cursor.fetchone()
        if result[0] == 1:
            return
        else:
            try:
                api.close_task(task_id=task_id)
                print(f"Task {task_id} marked as done in Todoist.")
                # change db entry to is_completed = 1
                cursor.execute('UPDATE tasks SET is_completed = 1 WHERE id = ?', (task_id,))
                conn.commit()     
            except Exception as error:
                print(f"Error updating task {task_id}: {error}")

def main():
    """Main function."""
    if not os.path.exists(DB_FILE):
        init_db()
    
    colors_dict = load_colors_from_csv(COLORS_FILE)
    
    collaborators = fetch_todoist_collaborators(todoist_api_token, todoist_projectid)
    if collaborators:
        new_collaborators_count = insert_collaborators_into_db(collaborators, colors_dict)
        print(f"{new_collaborators_count} new collaborators inserted into the database.")
    
    add_column_if_not_exists('tasks', 'assignee_firstname', 'TEXT')
    add_column_if_not_exists('tasks', 'assignee_hex_color', 'TEXT') 
    update_assignee_firstname()
    print("Assignee first names updated successfully.")

    tasks = fetch_todoist_tasks(todoist_api_token, todoist_projectid)
    if tasks:
        new_tasks_count = insert_tasks_into_db(tasks)
        print(f"{new_tasks_count} new tasks inserted into the database.")
        sync_tasks_to_miro()
    else:
        print("No tasks found or error fetching data.")

    done_frame_items = fetch_done_frame_items()
    if done_frame_items:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            for item in done_frame_items.data:
                miro_id = item.id
                cursor.execute('SELECT id FROM tasks WHERE miro_id = ?', (miro_id,))
                result = cursor.fetchone()
                if result:
                    complete_todoist_task(result[0])
    else:
        print("No done frame items found or error fetching data.")

if __name__ == "__main__":
    main()
