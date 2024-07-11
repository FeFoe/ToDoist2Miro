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
from pydantic import ValidationError

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
                hex_color TEXT,
                tag_id TEXT
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
                cursor.execute('''
                    INSERT OR IGNORE INTO collaborators (id, name, email, first_name)
                    VALUES (?, ?, ?, ?)
                ''', (collaborator.id, collaborator.name, collaborator.email, first_name))
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

def fetch_assignee_tag_id(cursor, assignee_id):
    """Fetch the tag ID of the assignee."""
    cursor.execute('SELECT tag_id FROM collaborators WHERE id = ?', (assignee_id,))
    result = cursor.fetchone()
    return result[0] if result else None


def color_name_to_hex(color_name):
    """Convert color name to hex code."""
    color_map = {
        'red': '#f24726',
        'green': '#8fd14f',
        'blue': '#2d9bf0',
        'yellow': '#fef445',
        'orange': '#fac710',
        'purple': '#652cb3',
        'black': '#000000',
        'white': '#FFFFFF',
        'gray': '#808080',
        'pink': '#FFC0CB',
        'light_green': '#cee741',
        'cyan': '#12cdd4',
        'magenta': '#da0063',
        'violet': '#9510ac',
        'dark_green': '#0ca789',
        'dark_blue': '#414bb2',
        # Add more colors as needed
    }
    return color_map.get(color_name.lower(), color_name)

def sync_tasks_to_miro():
    """Sync tasks to Miro."""
    api = miro_api.MiroApi(miro_access_token)
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Fetch tasks to sync with sync_status = 0
        cursor.execute('SELECT id, content, description, assignee_hex_color, due_date, assignee_id FROM tasks WHERE sync_status = 0')
        tasks_to_create = cursor.fetchall()

        max_per_column = 17
        card_width = 300
        card_height = 100
        horizontal_spacing = 10  # Abstand zwischen Spalten
        vertical_spacing = 1  # Abstand zwischen Zeilen

        # Fetch the coordinates of the frame "Eingang"
        x_offset, y_offset = fetch_frame_coordinates(miro_board_id, "Eingang")
        
        x_offset = x_offset + card_width /2 + 10
        y_offset = y_offset + card_height /2 + 5

        for idx, task in enumerate(tasks_to_create):
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

            card_theme_hex = color_name_to_hex(task[3])

            payload = {
                "data": {
                    "description": task[2],
                    "title": task[1],
                    "dueDate": due_date_formatted
                },
                "style": {
                    "cardTheme": card_theme_hex
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
            if response.status_code == 201:
                response_data = response.json()
                response_id = response_data.get('id')  # Extract the 'id' from the response

                cursor.execute('UPDATE tasks SET sync_status = 1, miro_id = ? WHERE id = ?', (response_id, task[0]))
                print(f"Card created for task {task[0]} with ID {response_id}.")
                assignee_tag_id = fetch_assignee_tag_id(cursor, task[5])
                if assignee_tag_id:
                    api.attach_tag_to_item(miro_board_id, response_id, assignee_tag_id)
            else:
                print(f"Failed to create card for task {task[0]} with code {response.status_code} Response: {response.json()}")

        # Fetch tasks to sync with sync_status = 2 (updates)
        cursor.execute('SELECT id, content, description, assignee_hex_color, due_date, miro_id, assignee_id FROM tasks WHERE sync_status = 2')
        tasks_to_update = cursor.fetchall()

        for task in tasks_to_update:
            task_id, content, description, assignee_hex_color, due_date, miro_id, assignee_id = task
            print(f"Updating task {task_id} with miro_id {miro_id}.")
            if update_miro_card(miro_id, content, description, due_date, assignee_hex_color):
                cursor.execute('UPDATE tasks SET sync_status = 1 WHERE id = ?', (task_id,))
                assignee_tag_id = fetch_assignee_tag_id(cursor, assignee_id)
                if assignee_tag_id:
                    api.attach_tag_to_item(miro_board_id, miro_id, assignee_tag_id)
        
        conn.commit()



def fetch_frame_coordinates(miro_board_id, frame_title):
    api = miro_api.MiroApi(miro_access_token)
    items = api.get_items(miro_board_id)

    # Use the provided logic to find the frame ID by its title
    rahmen_id = next((item.id for item in items.data if hasattr(item.data.actual_instance, 'title') and item.data.actual_instance.title == frame_title), None)

    if not rahmen_id:
        return None, None
    
    frame_item = api.get_specific_item(miro_board_id, rahmen_id)

    if hasattr(frame_item, 'position') and hasattr(frame_item, 'geometry'):
        position = frame_item.position
        geometry = frame_item.geometry
        
        # Extract center coordinates
        x_center = position.x
        y_center = position.y

        # Extract width and height
        width = geometry.width
        height = geometry.height

        # Calculate top-left position
        x_top_left = x_center - (width / 2)
        y_top_left = y_center - (height / 2)

        return x_top_left, y_top_left
    else:
        print(f"Error fetching frame coordinates: {frame_item}")
        return 0, 0






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


def get_existing_ids(table, column):
    """Get existing IDs from a specified table."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(f'SELECT {column} FROM {table}')
        return set(row[0] for row in cursor.fetchall())


def update_tasks_in_db(tasks):
    """Update tasks in the SQLite database."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            for task in tasks:
                # Prepare the values to be updated, with defaults if necessary
                content = task.get('content', '')
                project_id = task.get('project_id', None)
                due_date = task['due_date']
                due_datetime = task.get('due_datetime', None)
                due_string = task.get('due_string', None)
                due_timezone = task.get('due_timezone', None)
                creator_id = task.get('creator_id', None)
                created_at = task.get('created_at', None)
                assignee_id = task.get('assignee_id', None)
                assigner_id = task.get('assigner_id', None)
                comment_count = task.get('comment_count', 0)
                is_completed = int(task.get('is_completed', 0))
                description = task.get('description', '')
                labels = json.dumps(task.get('labels', []))
                order = task.get('order', 0)
                priority = task.get('priority', 1)
                section_id = task.get('section_id', None)
                parent_id = task.get('parent_id', None)
                url = task.get('url', '')
                duration_amount = task.get('duration_amount', None)
                duration_unit = task.get('duration_unit', None)
                owner = 'owner'  # Static value as per original code
                task_id = task.get('id')

                assignee_hex_color = fetch_assignee_hex_color(cursor, assignee_id) if assignee_id else '#ffffff'
                sync_status = 2

                if not task_id:
                    raise ValueError(f"Task ID is missing for task: {task}")

                cursor.execute('''
                    UPDATE tasks SET
                        content = ?, project_id = ?, due_date = ?, due_datetime = ?, due_string = ?, due_timezone = ?,
                        creator_id = ?, created_at = ?, assignee_id = ?, assigner_id = ?, comment_count = ?, is_completed = ?,
                        description = ?, labels = ?, "order" = ?, priority = ?, section_id = ?, parent_id = ?, url = ?,
                        duration_amount = ?, duration_unit = ?, owner = ?, assignee_hex_color = ?, sync_status = ?
                    WHERE id = ?
                ''', (
                    content, project_id, due_date, due_datetime, due_string, due_timezone,
                    creator_id, created_at, assignee_id, assigner_id, comment_count, is_completed,
                    description, labels, order, priority, section_id, parent_id, url,
                    duration_amount, duration_unit, owner, assignee_hex_color, sync_status, task_id
                ))
            conn.commit()
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

def fetch_todoist_tasks(api_token, project_id):
    """Fetch tasks from a specific Todoist project."""
    api = TodoistAPI(api_token)
    try:
        return api.get_tasks(project_id=project_id)
    except Exception as error:
        print(f"Error fetching tasks: {error}")
        return []

def fetch_tasks_from_db():
    """Fetch tasks from the SQLite database."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, content, project_id, due_date, due_datetime, due_string, due_timezone, creator_id, created_at, assignee_id, assigner_id, comment_count, is_completed, description, labels, "order", priority, section_id, parent_id, url, duration_amount, duration_unit, owner, sync_status, miro_id, assignee_firstname, assignee_hex_color FROM tasks')
        tasks = cursor.fetchall()
        # Map the results to a list of dictionaries for easy lookup
        task_list = []
        for row in tasks:
            task_list.append({
                'id': row[0],
                'content': row[1],
                'project_id': row[2],
                'due_date': row[3],
                'due_datetime': row[4],
                'due_string': row[5],
                'due_timezone': row[6],
                'creator_id': row[7],
                'created_at': row[8],
                'assignee_id': row[9],
                'assigner_id': row[10],
                'comment_count': row[11],
                'is_completed': row[12],
                'description': row[13],
                'labels': row[14],
                'order': row[15],
                'priority': row[16],
                'section_id': row[17],
                'parent_id': row[18],
                'url': row[19],
                'duration_amount': row[20],
                'duration_unit': row[21],
                'owner': row[22],
                'sync_status': row[23],
                'miro_id': row[24],
                'assignee_firstname': row[25],
                'assignee_hex_color': row[26]
            })
        return task_list
    

def update_miro_card(miro_id, title, description, due_date, card_theme):
    """Update a Miro card."""
    print(f"Updating Miro card {miro_id} with title {title}, description {description}, due date {due_date}, and card theme {card_theme}.")
    due_date_formatted = datetime.strptime(due_date, "%Y-%m-%d").isoformat() + 'Z' if due_date else None
    
    payload = {"data": {}, "style": {}}
    
    if title:
        payload["data"]["title"] = title
    if description:
        payload["data"]["description"] = description
    if due_date_formatted:
        payload["data"]["dueDate"] = due_date_formatted
    if card_theme:
        payload["style"]["cardTheme"] = color_name_to_hex(card_theme)
    
    if not payload["data"] and not payload["style"]:
        print(f"No updates needed for Miro card {miro_id}.")
        return True  # No changes needed


    headers = {
        'accept': 'application/json',
        'authorization': f'Bearer {miro_access_token}',
        'content-type': 'application/json',
    }
    
    response = requests.patch(f'https://api.miro.com/v2/boards/{miro_board_id}/cards/{miro_id}', headers=headers, json=payload)
    
    catch = response.json()
    if 'message' in catch:
        print(f"Error updating Miro card: {catch['message']}")
        return False
    
    return response.status_code == 200

def compare_and_update_tasks():
    """Compare and update tasks from Todoist to the database."""
    todoist_tasks = fetch_todoist_tasks(todoist_api_token, todoist_projectid)
    db_tasks = fetch_tasks_from_db()
    
    print(f"Fetched {len(todoist_tasks)} tasks from Todoist and {len(db_tasks)} tasks from the database.")

    # Map db tasks by id for quick lookup
    db_tasks_dict = {task['id']: task for task in db_tasks}

    tasks_to_update = []
    

    for todoist_task in todoist_tasks:
        db_task = db_tasks_dict.get(todoist_task.id)
        if db_task:
            # Compare fields and update if necessary
            todoist_due_date = todoist_task.due.date if todoist_task.due else None
            todoist_completed = int(todoist_task.is_completed)
            if (db_task['content'] != todoist_task.content or
                db_task['due_date'] != todoist_due_date or
                db_task['is_completed'] != todoist_completed or
                db_task['description'] != todoist_task.description or
                db_task['assignee_id'] != todoist_task.assignee_id):
                
                # Check if the assignee has been changed
                assignee_changed = db_task['assignee_id'] != todoist_task.assignee_id
                
                tasks_to_update.append({
                    'id': todoist_task.id,
                    'content': todoist_task.content,
                    'due_date': todoist_due_date,
                    'is_completed': todoist_completed,
                    'description': todoist_task.description,
                    'assignee_id': todoist_task.assignee_id,
                    'assignee_changed': assignee_changed
                })

    if tasks_to_update:
        print(f"Updating {len(tasks_to_update)} tasks in the database.")
        update_tasks_in_db(tasks_to_update)
    else:
        print("No tasks to update.")




def fetch_miro_tags():
    """Fetch tags from Miro board using MiroApi."""
    api = miro_api.MiroApi(miro_access_token)
    tags_response = api.get_tags_from_board(miro_board_id)
    if tags_response and hasattr(tags_response, 'data'):
        return tags_response.data
    else:
        print("Error: No tags data found in the response.")
        return []




def update_collaborator_hex_colors_and_tags(tags):
    """Update collaborator hex colors and tag IDs in the database based on Miro tags."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        for tag in tags:
            tag_name = tag.title
            tag_color = tag.fill_color
            tag_id = tag.id
            cursor.execute('''
                SELECT hex_color, tag_id
                FROM collaborators
                WHERE first_name LIKE ?
            ''', (tag_name,))
            result = cursor.fetchone()
            if result:
                current_color, current_tag_id = result
                if current_color != tag_color or current_tag_id != tag_id:
                    cursor.execute('''
                        UPDATE collaborators
                        SET hex_color = ?, tag_id = ?
                        WHERE first_name LIKE ?
                    ''', (tag_color, tag_id, tag_name))
                    print (f"Updating hex color and tag ID for collaborator {tag_name} to {tag_color} and {tag_id} from {current_color} and {current_tag_id}.")
                elif current_color != tag_color:
                    cursor.execute('''
                        UPDATE collaborators
                        SET hex_color = ?
                        WHERE first_name LIKE ?
                    ''', (tag_color, tag_name))
                    print(f"Updated hex color for collaborator {tag_name} to {tag_color}.")
                elif current_tag_id != tag_id:
                    cursor.execute('''
                        UPDATE collaborators
                        SET tag_id = ?
                        WHERE first_name LIKE ?
                    ''', (tag_id, tag_name))
                    print(f"Updated tag ID for collaborator {tag_name} to {tag_id}.")
            else:
                print(f"No collaborator found with the name {tag_name}.")
        conn.commit()


def create_tags_for_users_without_tags():
    """Create tags for users without tags in Miro."""
    api = miro_api.MiroApi(miro_access_token)
    existing_tags = fetch_miro_tags()
    existing_tag_titles = [tag.title for tag in existing_tags]

    # Define possible colors
    colors = ["light_green", "cyan", "yellow", "magenta", "green", "blue", "gray", "violet", "dark_green", "dark_blue"]
    used_colors = [tag.fill_color for tag in existing_tags]
    available_colors = [color for color in colors if color not in used_colors]

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT first_name FROM collaborators WHERE hex_color IS NULL OR hex_color = ""')
        collaborators_without_tags = cursor.fetchall()

        for collaborator in collaborators_without_tags:
            name = collaborator[0]
            if name not in existing_tag_titles:
                # Use a new color if available, otherwise reuse colors
                color = available_colors.pop(0) if available_colors else used_colors.pop(0)

                payload = {
                    "fillColor": color,
                    "title": name,
                }

                new_tag = api.create_tag(miro_board_id, payload)
                if new_tag:
                    tag_id = new_tag.id
                    cursor.execute('''
                        UPDATE collaborators
                        SET hex_color = ?, tag_id = ?
                        WHERE first_name = ?
                    ''', (color, tag_id, name))
                    conn.commit()
                    print(f"Tag created for {name} with color {color} and tag_id {tag_id}")



def main():
    """Main function."""
    if not os.path.exists(DB_FILE):
        init_db()

    collaborators = fetch_todoist_collaborators(todoist_api_token, todoist_projectid)
    if collaborators:
        new_collaborators_count = insert_collaborators_into_db(collaborators, {})
        print(f"{new_collaborators_count} new collaborators inserted into the database.")


    # Fetch tags from Miro and update collaborator colors
    miro_tags = fetch_miro_tags()
    if miro_tags:
        update_collaborator_hex_colors_and_tags(miro_tags)

    # Create tags for users without tags
    create_tags_for_users_without_tags()

    add_column_if_not_exists('tasks', 'assignee_firstname', 'TEXT')
    add_column_if_not_exists('tasks', 'assignee_hex_color', 'TEXT') 
    update_assignee_firstname()


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
    
    compare_and_update_tasks()
    sync_tasks_to_miro()

if __name__ == "__main__":
    main()