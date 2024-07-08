import sqlite3
import os
import json
from todoist_api_python.api import TodoistAPI
import hashlib
import math
import miro_api
from dotenv import load_dotenv
import os


# Load environment variables from .env file
load_dotenv()

# Access the environment variables
miro_access_token = os.getenv('MIRO_ACCESS_TOKEN')
miro_board_id = os.getenv('MIRO_BOARD_ID')
todoist_api_token = os.getenv('TODOIST_API_TOKEN')
todoist_projectid = os.getenv('TEAM_PROJECT_ID')

# SQLite Datenbank Datei
DB_FILE = 'todoist_tasks.db'

# Funktion um SQLite Datenbank zu initialisieren
def init_db(db_file):
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
            hex_color TEXT  -- Added column for hex color
        )
        ''')
        
    conn.commit()
    conn.close()

# Funktion um eine Spalte zu einer bestehenden Tabelle hinzuzufügen
def add_column_if_not_exists(db_file, table, column, column_type):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [info[1] for info in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    conn.commit()
    conn.close()

# Funktion um vorhandene Aufgaben-IDs aus der SQLite Datenbank zu holen
def get_existing_task_ids(db_file):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM tasks')
    rows = cursor.fetchall()
    conn.close()
    return set(row[0] for row in rows)

# Funktion um Aufgaben in die SQLite Datenbank einzufügen
def insert_tasks_into_db(db_file, tasks):
    existing_task_ids = get_existing_task_ids(db_file)
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    new_tasks_count = 0
    for task in tasks:
        if task.id not in existing_task_ids:
            # Fetch hex color for assignee
            assignee_hex_color = fetch_assignee_hex_color(conn, cursor, task.assignee_id)
            
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
                task.creator_id, task.created_at, task.assignee_id, 
                task.assigner_id, task.comment_count, 
                int(task.is_completed), task.description, 
                json.dumps(task.labels), task.order, task.priority, 
                task.section_id, task.parent_id, task.url, 
                task.duration.amount if hasattr(task, 'duration') and task.duration else None,
                task.duration.unit if hasattr(task, 'duration') and task.duration else None,
                'owner', 0, None,
                assignee_hex_color  # Insert hex color here
            ))
            new_tasks_count += 1
    conn.commit()
    conn.close()
    return new_tasks_count

# Funktion um vorhandene Kollaborator-IDs aus der SQLite Datenbank zu holen
def get_existing_collaborator_ids(db_file):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM collaborators')
    rows = cursor.fetchall()
    conn.close()
    return set(row[0] for row in rows)

# Funktion um den Vornamen zu extrahieren
def extract_first_name(full_name):
    separators = [' ', '.']
    for sep in separators:
        if sep in full_name:
            return full_name.split(sep)[0].capitalize().strip()
    return full_name.capitalize().strip()

# Funktion zur Erzeugung einer Hex-Farbe aus einem String
def generate_hex_color(name):
    # Use MD5 hash to generate a unique color for the name
    color_hash = hashlib.md5(name.encode()).hexdigest()
    # Take the first 6 characters of the hash to form a hex color code
    return '#' + color_hash[:6]

# Funktion zum Abrufen der Hex-Farbe des Assignees
def fetch_assignee_hex_color(conn, cursor, assignee_id):
    cursor.execute('''
    SELECT hex_color
    FROM collaborators
    WHERE id = ?
    ''', (assignee_id,))
    result = cursor.fetchone()
    if result:
        return result[0]
    else:
        # If no hex color is found, generate one based on a default name
        return generate_hex_color("Unknown Assignee")

# Funktion um Kollaboratoren in die SQLite Datenbank einzufügen
def insert_collaborators_into_db(db_file, collaborators):
    existing_collaborator_ids = get_existing_collaborator_ids(db_file)
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    new_collaborators_count = 0
    for collaborator in collaborators:
        if collaborator.id not in existing_collaborator_ids:
            first_name = extract_first_name(collaborator.name)
            hex_color = generate_hex_color(collaborator.name)
            cursor.execute('''
            INSERT OR IGNORE INTO collaborators (id, name, email, first_name, hex_color)
            VALUES (?, ?, ?, ?, ?)
            ''', (collaborator.id, collaborator.name, collaborator.email, first_name, hex_color))
            new_collaborators_count += 1
    conn.commit()
    conn.close()
    return new_collaborators_count

# Funktion um Aufgaben von einem spezifischen Todoist-Projekt zu holen
def fetch_todoist_tasks(api_token, project_id):
    api = TodoistAPI(api_token)
    try:
        tasks = api.get_tasks(project_id=project_id)
        return tasks
    except Exception as error:
        print(f"Fehler beim Abrufen der Daten: {error}")
        return None

# Funktion um Kollaboratoren von einem spezifischen Todoist-Projekt zu holen
def fetch_todoist_collaborators(api_token, project_id):
    api = TodoistAPI(api_token)
    try:
        collaborators = api.get_collaborators(project_id=project_id)
        return collaborators
    except Exception as error:
        print(f"Fehler beim Abrufen der Kollaboratoren: {error}")
        return None

# Funktion um den Vornamen des Assignees in der tasks-Tabelle zu aktualisieren
def update_assignee_firstname(db_file):
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
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('SELECT id, content, description, assignee_hex_color FROM tasks WHERE sync_status = 0')
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def sync_tasks_to_miro(db_file, access_token, board_id):
    api = miro_api.MiroApi(access_token)
    tasks = fetch_tasks_to_sync(db_file)
    
    # Determine grid layout parameters
    max_per_column = 15  # Maximum number of cards per column
    card_width = 300  # Width of each card
    card_height = 100  # Height of each card
    horizontal_spacing = 10  # Horizontal spacing between cards
    vertical_spacing = 10  # Vertical spacing between cards
    
    for idx, task in enumerate(tasks):
        column_index = idx // max_per_column  # Calculate current column index
        row_index = idx % max_per_column  # Calculate current row index within the column
        
        x_position = column_index * (card_width + horizontal_spacing)
        y_position = row_index * (card_height + vertical_spacing)
        
        payload = {
            "data": {
                "description": task[2],  # task description
                "title": task[1]  # task content
            },
            "style": {
                "cardTheme": task[3]  # task hex color
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
        
        # Update sync_status to 1 in SQLite
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute('UPDATE tasks SET sync_status = 1 WHERE id = ?', (task[0],))
        conn.commit()
        conn.close()


# Hauptfunktion
def main():
    if not os.path.exists(DB_FILE):
        init_db(DB_FILE)
    
    collaborators = fetch_todoist_collaborators(todoist_api_token, todoist_projectid)
    if collaborators:
        new_collaborators_count = insert_collaborators_into_db(DB_FILE, collaborators)
        print(f"{new_collaborators_count} neue Kollaboratoren erfolgreich in die Datenbank eingefügt.")
    else:
        print("Keine Kollaboratoren gefunden oder Fehler beim Abrufen der Daten.")
    


    add_column_if_not_exists(DB_FILE, 'tasks', 'assignee_firstname', 'TEXT')
    add_column_if_not_exists(DB_FILE, 'tasks', 'assignee_hex_color', 'TEXT') 
    update_assignee_firstname(DB_FILE)


    print("Assignee-Vornamen erfolgreich aktualisiert.")

    tasks = fetch_todoist_tasks(todoist_api_token, todoist_projectid)
    if tasks:
        new_tasks_count = insert_tasks_into_db(DB_FILE, tasks)
        print(f"{new_tasks_count} neue Aufgaben erfolgreich in die Datenbank eingefügt.")
        sync_tasks_to_miro(DB_FILE, miro_access_token, miro_board_id)  # Sync tasks to Miro
    else:
        print("Keine Aufgaben gefunden oder Fehler beim Abrufen der Daten.")

    
    

if __name__ == "__main__":
    main()
