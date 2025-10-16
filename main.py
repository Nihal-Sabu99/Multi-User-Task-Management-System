from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import google.oauth2.id_token
from google.auth.transport import requests
from google.cloud import firestore
import starlette.status as status
from datetime import datetime
from typing import List, Optional

# Initializing FastAPI app
app=FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates=Jinja2Templates(directory="templates")

# Initializing Firestore
try:
    db=firestore.Client()
    print("Firestore initialized successfully")
except Exception as e:
    print(f"Error initializing Firestore: {e}")

# Verifying Google ID token
async def verify_token(request: Request):
    token =""
    if "token" in request.cookies:
        token=request.cookies.get("token")
    
    if not token:
        return None
    
    try:
        auth_req=requests.Request()
        decoded_token=google.oauth2.id_token.verify_firebase_token(token, auth_req)
        return decoded_token
    except Exception as e:
        print(f"Token verification error: {e}")
        return None

# User email from the token
async def get_user_email(token_data):
    if not token_data:
        return None
    return token_data.get("email", None)

# Checking the user is authenticated
async def is_authenticated(request: Request):
    token_data=await verify_token(request)
    return token_data is not None

# Current user
async def get_current_user(request: Request):
    token_data=await verify_token(request)
    if not token_data:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return token_data

# Home page
@app.get("/", response_class=HTMLResponse)
async def home(request:Request):
    token_data=await verify_token(request)
    if not token_data:
        return templates.TemplateResponse("login.html", {"request":request})
    
    user_email=await get_user_email(token_data)
    if not user_email:
        return templates.TemplateResponse("login.html", {"request":request})
    
    #User boards
    user_boards=[]
    
    # Boards created
    boards_ref=db.collection("boards").where("creator", "==", user_email).stream()
    for board in boards_ref:
        board_data=board.to_dict()
        board_data["id"]=board.id
        board_data["is_creator"]=True
        user_boards.append(board_data)
    
    # Boards where user is a member
    boards_ref=db.collection("boards").where("members", "array_contains", user_email).stream()
    for board in boards_ref:
        if any(b["id"]==board.id for b in user_boards):
            continue
        
        board_data=board.to_dict()
        board_data["id"]=board.id
        board_data["is_creator"]=False
        user_boards.append(board_data)

    return templates.TemplateResponse(
        "dashboard.html", 
        {
            "request":request, 
            "user_email":user_email,
            "boards":user_boards
        }
    )

# Login page
@app.get("/login", response_class=HTMLResponse)
async def login_page(request:Request):
    is_auth=await is_authenticated(request)
    if is_auth:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request":request})

# Sign-up page
@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request:Request):
    is_auth=await is_authenticated(request)
    if is_auth:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("signup.html", {"request":request})

# Creating board
@app.post("/create_board")
async def create_board(
    request:Request,
    board_name:str=Form(...),
    description:str=Form(...)
):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    if not user_email:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    new_board={
        "name":board_name,
        "description":description,
        "creator":user_email,
        "members":[], 
        "created_at":firestore.SERVER_TIMESTAMP
    }
    
    db.collection("boards").add(new_board)
    
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

# Board page
@app.get("/create_board", response_class=HTMLResponse)
async def create_board_page(request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    return templates.TemplateResponse(
        "create_board.html", 
        {
            "request":request,
            "user_email":user_email
        }
    )

# Board details page
@app.get("/board/{board_id}", response_class=HTMLResponse)
async def view_board(board_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    # Taking board data
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    board_data["id"]=board_id

    # Check if the user is a creator or a member
    if user_email !=board_data["creator"] and user_email not in board_data["members"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this board")
    is_creator=(user_email==board_data["creator"])
    
    tasks=[]
    tasks_ref=db.collection("boards").document(board_id).collection("tasks").stream()
    
    active_count=0
    completed_count=0

    for task in tasks_ref:
        task_data=task.to_dict()
        task_data["id"]=task.id
        # Check if task is completed
        if task_data.get("completed", False):
            completed_count +=1
        else:
            active_count +=1

        task_data["unassigned"]=len(task_data.get("assignees", []))==0
        tasks.append(task_data)

    total_count=active_count + completed_count

    return templates.TemplateResponse(
        "board_detail.html", 
        {
            "request":request,
            "user_email":user_email,
            "board":board_data,
            "tasks":tasks,
            "is_creator":is_creator,
            "active_count":active_count,
            "completed_count":completed_count,
            "total_count":total_count
        }
    )

# Board members page
@app.get("/board/{board_id}/members", response_class=HTMLResponse)
async def board_members_page(board_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    board_data["id"]=board_id
    
    # Checking if the user is a creator or member
    if user_email !=board_data["creator"] and user_email not in board_data["members"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this board")
    
    is_creator=(user_email==board_data["creator"])
    
    return templates.TemplateResponse(
        "board_members.html", 
        {
            "request":request,
            "user_email":user_email,
            "board":board_data,
            "is_creator":is_creator
        }
    )

# Adding member to the board
@app.post("/board/{board_id}/add_member")
async def add_member(
    board_id:str,
    request:Request,
    member_email:str=Form(...)
):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"]:
        raise HTTPException(status_code=403, detail="Only the board creator can add members")
    
    # Checking if the member is already in the board
    if member_email==board_data["creator"] or member_email in board_data["members"]:
        raise HTTPException(status_code=400, detail="User is already a member of this board")
    
    # Adding member to the board
    board_ref.update({
        "members":firestore.ArrayUnion([member_email])
    })
    
    return RedirectResponse(url=f"/board/{board_id}/members", status_code=303)

# Remove member from the board
@app.post("/board/{board_id}/remove_member")
async def remove_member(
    board_id:str,
    request:Request,
    member_email:str=Form(...)
):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)

    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"]:
        raise HTTPException(status_code=403, detail="Only the board creator can remove members")

    if member_email not in board_data["members"]:
        raise HTTPException(status_code=400, detail="User is not a member of this board")
    
    # Removing member from the board
    board_ref.update({
        "members":firestore.ArrayRemove([member_email])
    })

    # Mark tasks assigned to the removed user as unassigned.
    tasks_ref=db.collection("boards").document(board_id).collection("tasks").stream()
    
    for task in tasks_ref:
        task_data=task.to_dict()
        if member_email in task_data.get("assignees", []):
            db.collection("boards").document(board_id).collection("tasks").document(task.id).update({
                "assignees": firestore.ArrayRemove([member_email])
            })

    return RedirectResponse(url=f"/board/{board_id}/members", status_code=303)

# Board settings page
@app.get("/board/{board_id}/settings", response_class=HTMLResponse)
async def board_settings_page(board_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    board_data["id"]=board_id
    
    if user_email !=board_data["creator"]:
        raise HTTPException(status_code=403, detail="Only the board creator can access settings")

    task_count=0
    tasks_ref=db.collection("boards").document(board_id).collection("tasks").stream()
    for _ in tasks_ref:
        task_count +=1
    
    can_delete=len(board_data["members"])==0 and task_count==0
    
    return templates.TemplateResponse(
        "board_settings.html", 
        {
            "request":request,
            "user_email":user_email,
            "board":board_data,
            "task_count":task_count,
            "member_count":len(board_data["members"]),
            "can_delete":can_delete
        }
    )

# Update the board
@app.post("/board/{board_id}/update_settings")
async def update_board_settings(
    board_id:str,
    request:Request,
    board_name:str=Form(...),
    description:str=Form(...)
):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)

    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"]:
        raise HTTPException(status_code=403, detail="Only the board creator can update settings")
    
    board_ref.update({
        "name":board_name,
        "description":description
    })
    
    return RedirectResponse(url=f"/board/{board_id}/settings", status_code=303)

# Delete the board
@app.post("/board/{board_id}/delete")
async def delete_board(board_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"]:
        raise HTTPException(status_code=403, detail="Only the board creator can delete the board")
    
    # Checking if the board has members
    if len(board_data["members"])>0:
        raise HTTPException(status_code=400, detail="Cannot delete board with members")
    
    # Check if board has tasks
    tasks_ref=db.collection("boards").document(board_id).collection("tasks").stream()
    tasks=list(tasks_ref)
    if len(tasks) > 0:
        raise HTTPException(status_code=400, detail="Cannot delete board with tasks")
     
    board_ref.delete()
    
    return RedirectResponse(url="/", status_code=303)

# Create task
@app.post("/board/{board_id}/add_task")
async def add_task(
    board_id:str,
    request:Request,
    title:str=Form(...),
    description:str=Form(""),
    due_date:str=Form(...),
    assignees:Optional[List[str]]=Form([])
):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)

    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()

    if user_email !=board_data["creator"] and user_email not in board_data["members"]:
        raise HTTPException(status_code=403, detail="Not authorized to add tasks to this board")
    
    # Create new task
    new_task = {
        "title":title,
        "description":description,
        "due_date":due_date,
        "created_by":user_email,
        "created_at":firestore.SERVER_TIMESTAMP,
        "completed":False,
        "completed_at":None,
        "assignees":assignees if assignees else []
    }
    
    db.collection("boards").document(board_id).collection("tasks").add(new_task)
    
    return RedirectResponse(url=f"/board/{board_id}", status_code=303)

# Page for adding tasks
@app.get("/board/{board_id}/add_task", response_class=HTMLResponse)
async def add_task_page(board_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    board_data["id"]=board_id
    
    is_creator=(user_email==board_data["creator"])

    # Board members for selecting assignee
    members=board_data["members"].copy()
    members.append(board_data["creator"])
    
    return templates.TemplateResponse(
        "add_task.html", 
        {
            "request":request,
            "user_email":user_email,
            "board":board_data,
            "members":members,
            "is_creator":is_creator
        }
    )

# Task details page
@app.get("/board/{board_id}/task/{task_id}", response_class=HTMLResponse)
async def view_task(board_id:str, task_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    board_data["id"]=board_id

    if user_email !=board_data["creator"] and user_email not in board_data["members"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this board")
    
    task_ref=db.collection("boards").document(board_id).collection("tasks").document(task_id)
    task=task_ref.get()
    
    if not task.exists:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_data=task.to_dict()
    task_data["id"]=task_id

    if task_data.get("completed_at"):
        timestamp=task_data["completed_at"]
        if hasattr(timestamp, "strftime"):
            task_data["completed_at"]=timestamp.strftime("%Y-%m-%d %H:%M:%S")

    task_data["unassigned"]=len(task_data.get("assignees", []))==0
    
    # Board members for selecting assignee.
    members=board_data["members"].copy()
    members.append(board_data["creator"])
    
    is_creator=(user_email==board_data["creator"])
    
    return templates.TemplateResponse(
        "task_detail.html", 
        {
            "request":request,
            "user_email":user_email,
            "board":board_data,
            "task":task_data,
            "members":members,
            "is_creator":is_creator
        }
    )

# Editing tasks
@app.post("/board/{board_id}/task/{task_id}/edit")
async def edit_task(
    board_id:str,
    task_id:str,
    request:Request,
    title:str=Form(...),
    description:str=Form(""),
    due_date:str=Form(...),
    status:str=Form("incomplete")
):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"] and user_email not in board_data["members"]:
        raise HTTPException(status_code=403, detail="Not authorized to modify this task")
    
    task_ref=db.collection("boards").document(board_id).collection("tasks").document(task_id)
    task=task_ref.get()
    
    if not task.exists:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Update status
    is_completed=status=="complete"
    
    # If status changed to complete, set completed.
    completed_at=None
    if is_completed:
        completed_at=firestore.SERVER_TIMESTAMP
    
    task_ref.update({
        "title":title,
        "description":description,
        "due_date":due_date,
        "completed":is_completed,
        "completed_at":completed_at
    })
    
    return RedirectResponse(url=f"/board/{board_id}/task/{task_id}", status_code=303)

# Page for editing tasks.
@app.get("/board/{board_id}/task/{task_id}/edit", response_class=HTMLResponse)
async def edit_task_page(board_id:str, task_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    board_data["id"]=board_id
    
    if user_email !=board_data["creator"] and user_email not in board_data["members"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this board")
    
    task_ref=db.collection("boards").document(board_id).collection("tasks").document(task_id)
    task=task_ref.get()
    
    if not task.exists:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_data=task.to_dict()
    task_data["id"]=task_id

    members=board_data["members"].copy()
    members.append(board_data["creator"])
    
    is_creator=(user_email==board_data["creator"])
    
    return templates.TemplateResponse(
        "edit_task.html", 
        {
            "request":request,
            "user_email":user_email,
            "board":board_data,
            "task":task_data,
            "members":members,
            "is_creator":is_creator
        }
    )

# Task completion function
@app.post("/board/{board_id}/task/{task_id}/complete")
async def complete_task(board_id:str, task_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"] and user_email not in board_data["members"]:
        raise HTTPException(status_code=403, detail="Not authorized to modify this task")
    
    task_ref=db.collection("boards").document(board_id).collection("tasks").document(task_id)
    task=task_ref.get()
    
    if not task.exists:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Mark task as complete
    task_ref.update({
        "completed":True,
        "completed_at":firestore.SERVER_TIMESTAMP
    })
    
    return RedirectResponse(url=f"/board/{board_id}", status_code=303)

# Task deletion 
@app.post("/board/{board_id}/task/{task_id}/delete")
async def delete_task(board_id:str, task_id:str, request:Request):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"] and user_email not in board_data["members"]:
        raise HTTPException(status_code=403, detail="Not authorized to delete this task")
    
    # Delete task
    db.collection("boards").document(board_id).collection("tasks").document(task_id).delete()
    
    return RedirectResponse(url=f"/board/{board_id}", status_code=303)

# Assigning user to the task
@app.post("/board/{board_id}/task/{task_id}/assign")
async def assign_user(
    board_id:str,
    task_id:str,
    request:Request,
    assignee:str=Form(...)
):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"]:
        raise HTTPException(status_code=403, detail="Only the board creator can assign users to tasks")
    
    if assignee !=board_data["creator"] and assignee not in board_data["members"]:
        raise HTTPException(status_code=400, detail="Assignee is not a member of this board")
    
    task_ref=db.collection("boards").document(board_id).collection("tasks").document(task_id)
    task=task_ref.get()
    
    if not task.exists:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_data=task.to_dict()
    
    # Adding assignee to the task
    assignees=task_data.get("assignees", [])
    if assignee not in assignees:
        assignees.append(assignee)
    
    task_ref.update({
        "assignees":assignees
    })
    
    return RedirectResponse(url=f"/board/{board_id}/task/{task_id}", status_code=303)

# Removing assignee from the task.
@app.post("/board/{board_id}/task/{task_id}/unassign")
async def unassign_user(
    board_id:str,
    task_id:str,
    request:Request,
    assignee:str=Form(...)
):
    token_data=await get_current_user(request)
    user_email=await get_user_email(token_data)
    
    board_ref=db.collection("boards").document(board_id)
    board=board_ref.get()
    
    if not board.exists:
        raise HTTPException(status_code=404, detail="Board not found")
    
    board_data=board.to_dict()
    
    if user_email !=board_data["creator"]:
        raise HTTPException(status_code=403, detail="Only the board creator can unassign users from tasks")
    
    task_ref=db.collection("boards").document(board_id).collection("tasks").document(task_id)
    task=task_ref.get()
    
    if not task.exists:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_data=task.to_dict()
    
    # Remove assignee from the task
    assignees=task_data.get("assignees", [])
    if assignee in assignees:
        assignees.remove(assignee)
    
    # Update the task with the new assignees.
    task_ref.update({
        "assignees":assignees
    })
    
    return RedirectResponse(url=f"/board/{board_id}/task/{task_id}", status_code=303)
