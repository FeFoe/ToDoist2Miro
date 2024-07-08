import sqlite3
import os
import json
import hashlib
from todoist_api_python.api import TodoistAPI
from dotenv import load_dotenv
import miro_api
import pandas as pd

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

def init_db(db_file):
    """Initialize the SQLite database."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
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
        assignee_firstname TEXT,
        assignee_hex_color TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS collaborators (
        id TEXT PRIMARY KEY,
        name TEXT,
        email TEXT,
        first_name TEXT,
        hex_color TEXT
    )
    ''')
        
    conn.commit()
    conn.close()

def add_column_if_not_exists(db_file, table, column, column_type):
    """Add a column to an existing table if it does not exist."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [info[1] for info in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    conn.commit()
    conn.close()

def get_existing_ids(db_file, table, column):
    """Get existing IDs from a specified table."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute(f'SELECT {column} FROM {table}')
    rows = cursor.fetchall()
    conn.close()
    return set(row[0] for row in rows)

def insert_tasks_into_db(db_file, tasks):
    """Insert tasks into the SQLite database."""
    existing_task_ids = get_existing_ids(db_file, 'tasks', 'id')
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    new_tasks_count = 0
    for task in tasks:
        if task.id not in existing_task_ids:
            assignee_id = task.assignee_id 
            assignee_hex_color = fetch_assignee_hex_color(cursor, assignee_id) if task.assignee_id else '#ffffff'
            duration_amount = None
            duration_unit = None
            if hasattr(task, 'duration') and task.duration:
                duration_amount = task.duration.get('amount')
                duration_unit = task.duration.get('unit')
            
            cursor.execute('''
            INSERT OR IGNORE INTO tasks (
                id, content, project_id, due_date, due_datetime, due_string, due_timezone,
                creator_id, created_at, assignee_id, assigner_id, comment_count, is_completed,
                description, labels, "order", priority, section_id, parent_id, url,
                duration_amount, duration_unit, owner, sync_status, assignee_firstname,
                assignee_hex_color
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                'owner', 0, None,
                assignee_hex_color
            ))
            new_tasks_count += 1
    conn.commit()
    conn.close()
    return new_tasks_count


def insert_collaborators_into_db(db_file, collaborators, colors_dict):
    """Insert collaborators into the SQLite database."""
    existing_collaborator_ids = get_existing_ids(db_file, 'collaborators', 'id')
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    new_collaborators_count = 0
    for collaborator in collaborators:
        if collaborator.id not in existing_collaborator_ids:
            first_name = extract_first_name(collaborator.name)
            hex_color = colors_dict.get(int(collaborator.id)) or generate_hex_color(collaborator.name)
            cursor.execute('''
            INSERT OR IGNORE INTO collaborators (id, name, email, first_name, hex_color)
            VALUES (?, ?, ?, ?, ?)
            ''', (collaborator.id, collaborator.name, collaborator.email, first_name, hex_color))
            new_collaborators_count += 1
    conn.commit()
    conn.close()
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

def update_assignee_firstname(db_file):
    """Update the first name of the assignee in the tasks table."""
    conn = sqlite3.connect(db_file)
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
    conn.close()

def fetch_tasks_to_sync(db_file):
    """Fetch tasks to sync from the SQLite database."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('SELECT id, content, description, assignee_hex_color FROM tasks WHERE sync_status = 0')
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def sync_tasks_to_miro(db_file, access_token, board_id):
    """Sync tasks to Miro."""
    api = miro_api.MiroApi(access_token)
    tasks = fetch_tasks_to_sync(db_file)
    
    max_per_column = 15
    card_width = 300
    card_height = 100
    horizontal_spacing = 10
    vertical_spacing = 10
    
    for idx, task in enumerate(tasks):
        column_index = idx // max_per_column
        row_index = idx % max_per_column
        
        x_position = column_index * (card_width + horizontal_spacing)
        y_position = row_index * (card_height + vertical_spacing)
        
        payload = {
            "data": {
                "description": task[2],
                "title": task[1]
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
        
        api.create_card_item(board_id, payload)
        
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute('UPDATE tasks SET sync_status = 1 WHERE id = ?', (task[0],))
        conn.commit()
        conn.close()

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
        colors_dict = dict(zip(colors_df['id'], colors_df['hex']))
        return colors_dict
    return {}

def fetch_done_frame_items(board_id, access_token):
    """Fetch items from the 'done' frame in Miro."""
    api = miro_api.MiroApi(access_token)
    items = api.get_items(board_id)

    rahmen_id = None
    for item in items.data:
        actual_instance = item.data.actual_instance
        if hasattr(actual_instance, 'title') and actual_instance.title == "Done":
            rahmen_id = item.id
            break

    if rahmen_id:
        return api.get_items_within_frame(board_id, rahmen_id)
    else:
        print("Done frame not found.")
        return []

def complete_todoist_task(api_token, task_id):
    """Update a Todoist task."""
    api = TodoistAPI(api_token)p
    try:
        api.close_task(task_id=task_id)
        print(f"Task {task_id} marked as done in Todoist.")
    except Exception as error:
        print(f"Error updating task {task_id}: {error}")

def main():
    """Main function."""
    if not os.path.exists(DB_FILE):
        init_db(DB_FILE)
    
    colors_dict = load_colors_from_csv(COLORS_FILE)
    
    collaborators = fetch_todoist_collaborators(todoist_api_token, todoist_projectid)
    if collaborators:
        new_collaborators_count = insert_collaborators_into_db(DB_FILE, collaborators, colors_dict)
        print(f"{new_collaborators_count} new collaborators inserted into the database.")
    else:
        print("No collaborators found or error fetching data.")
    
    add_column_if_not_exists(DB_FILE, 'tasks', 'assignee_firstname', 'TEXT')
    add_column_if_not_exists(DB_FILE, 'tasks', 'assignee_hex_color', 'TEXT') 
    update_assignee_firstname(DB_FILE)
    print("Assignee first names updated successfully.")

    tasks = fetch_todoist_tasks(todoist_api_token, todoist_projectid)
    if tasks:
        new_tasks_count = insert_tasks_into_db(DB_FILE, tasks)
        print(f"{new_tasks_count} new tasks inserted into the database.")
        sync_tasks_to_miro(DB_FILE, miro_access_token, miro_board_id)
    else:
        print("No tasks found or error fetching data.")

    done_frame_items = fetch_done_frame_items(miro_board_id, miro_access_token)
    if done_frame_items:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        api = miro_api.MiroApi(miro_access_token)

        # Iterate through each item in the data attribute of done_frame_items
        for item in done_frame_items.data:
            title = item.data.title if hasattr(item.data, 'title') else None
            description = item.data.description if hasattr(item.data, 'description') else None
            print(f"Title: {title}, Description: {description}")
            # Check if the description is None and execute the appropriate SQL query
            if description is None:
                cursor.execute('SELECT id FROM tasks WHERE content LIKE ?', (title,))
            else:
                cursor.execute('SELECT id FROM tasks WHERE content LIKE ? AND description LIKE ?', (title, description))
            
            result = cursor.fetchone()
            print(f"Result: {result}")
            if result:
                complete_todoist_task(todoist_api_token, result[0])

        conn.close()



    else:
        print("No done frame items found or error fetching data.")

if __name__ == "__main__":
    main()
