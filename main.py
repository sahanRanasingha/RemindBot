import asyncio
import logging
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, filters
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a scheduler
scheduler = BackgroundScheduler()

# Store tasks in a dictionary (user_id: [task_info])
tasks = {}
expired_tasks = {}

# Task state
USER_TASK_STATE = {}
EDIT_TASK_INDEX = {}

# Store scheduled jobs
SCHEDULED_JOBS = {}

# Function to start the bot and handle /start command
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text('Welcome to the Task Manager Bot! Use /add_reminder to schedule a reminder, /view_reminders to view all your reminders, /view_expired to view expired reminders, /edit_reminders to edit a reminder, and /delete_reminder to delete a reminder.')

# Function to initiate the reminder addition
async def add_reminder(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text('Please send me the reminder name.')

    # Set task state to 'name' to start the reminder creation flow
    USER_TASK_STATE[update.message.from_user.id] = 'name'

# Function to handle the input of reminder details
async def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    state = USER_TASK_STATE.get(user_id)
    task_index = EDIT_TASK_INDEX.get(user_id)

    if state == 'name':
        reminder_name = update.message.text
        if task_index is not None:  # Editing an existing reminder
            tasks[user_id][task_index]['reminder_name'] = reminder_name
            USER_TASK_STATE[user_id] = 'description'
        else:  # Adding a new reminder
            USER_TASK_STATE[user_id] = 'description'
            tasks.setdefault(user_id, [])
            tasks[user_id].append({'reminder_name': reminder_name})

        await update.message.reply_text(f"Reminder name set as: {reminder_name}. Now, please send me the reminder description.")

    elif state == 'description':
        reminder_description = update.message.text
        if task_index is not None:  # Editing an existing reminder
            tasks[user_id][task_index]['reminder_description'] = reminder_description
            USER_TASK_STATE[user_id] = 'date'
        else:  # Adding a new reminder
            USER_TASK_STATE[user_id] = 'date'
            tasks[user_id][-1]['reminder_description'] = reminder_description

        await update.message.reply_text(f"Reminder description set as: {reminder_description}. Now, please send me the date (YYYY-MM-DD).")

    elif state == 'date':
        try:
            reminder_date = datetime.datetime.strptime(update.message.text, '%Y-%m-%d').date()
            if task_index is not None:  # Editing an existing reminder
                tasks[user_id][task_index]['reminder_date'] = reminder_date
                USER_TASK_STATE[user_id] = 'time'
            else:  # Adding a new reminder
                USER_TASK_STATE[user_id] = 'time'
                tasks[user_id][-1]['reminder_date'] = reminder_date

            await update.message.reply_text(f"Reminder date set as: {reminder_date}. Now, please send me the time (HH:MM).")

        except ValueError:
            await update.message.reply_text("Invalid format. Please send the date in this format: YYYY-MM-DD.")

    elif state == 'time':
        try:
            reminder_time = datetime.datetime.strptime(update.message.text, '%H:%M').time()
            if task_index is not None:  # Editing an existing reminder
                tasks[user_id][task_index]['reminder_time'] = reminder_time
                reminder_name = tasks[user_id][task_index]['reminder_name']
                reminder_description = tasks[user_id][task_index]['reminder_description']
                reminder_date = tasks[user_id][task_index]['reminder_date']
                reminder_datetime = datetime.datetime.combine(reminder_date, reminder_time)

                # Remove existing job if it exists
                if user_id in SCHEDULED_JOBS and task_index in SCHEDULED_JOBS[user_id]:
                    SCHEDULED_JOBS[user_id][task_index].remove()

                # Reschedule the reminder
                job = scheduler.add_job(send_reminder_wrapper, DateTrigger(run_date=reminder_datetime), args=[update, user_id])
                SCHEDULED_JOBS.setdefault(user_id, {})[task_index] = job

                # Clear the task state and edit index after completion
                del USER_TASK_STATE[user_id]
                del EDIT_TASK_INDEX[user_id]

            else:  # Adding a new reminder
                USER_TASK_STATE[user_id] = 'done'
                tasks[user_id][-1]['reminder_time'] = reminder_time

                reminder_name = tasks[user_id][-1]['reminder_name']
                reminder_description = tasks[user_id][-1]['reminder_description']
                reminder_date = tasks[user_id][-1]['reminder_date']
                reminder_datetime = datetime.datetime.combine(reminder_date, reminder_time)

                # Schedule the reminder
                job = scheduler.add_job(send_reminder_wrapper, DateTrigger(run_date=reminder_datetime), args=[update, user_id])
                SCHEDULED_JOBS.setdefault(user_id, {})[len(tasks[user_id]) - 1] = job

                # Clear the task state after completion
                del USER_TASK_STATE[user_id]

            await update.message.reply_text(f"Reminder '{reminder_name}' set for {reminder_datetime}. The reminder will be sent at this time.")

        except ValueError:
            await update.message.reply_text("Invalid format. Please send the time in this format: HH:MM.")

# Function to send a reminder to the user
async def send_reminder(update: Update, user_id):
    task = tasks.get(user_id, [])
    if task:
        task = task.pop(0)  # Get and remove the earliest task
        reminder_name = task['reminder_name']
        reminder_description = task['reminder_description']
        reminder_date = task['reminder_date']
        reminder_time = task['reminder_time']

        # Send back full reminder details
        await update.message.reply_text(f"Reminder: Your reminder '{reminder_name}' is due now!\n"
                                       f"Description: {reminder_description}\n"
                                       f"Scheduled Date: {reminder_date}\n"
                                       f"Scheduled Time: {reminder_time}")

        # Move the task to expired tasks
        expired_tasks.setdefault(user_id, []).append(task)
    else:
        await update.message.reply_text("Reminder not found!")

# Synchronous wrapper function to call the asynchronous send_reminder function
def send_reminder_wrapper(update: Update, user_id):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_reminder(update, user_id))
    loop.close()

# Function to view all reminders for a user
async def view_reminders(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_tasks = tasks.get(user_id, [])

    if not user_tasks:
        await update.message.reply_text("You don't have any reminders set.")
    else:
        response = "Your reminders:\n"
        for i, task in enumerate(user_tasks):
            response += f"\n{str(i + 1)}. {task['reminder_name']} - {task['reminder_description']} (Scheduled at: {task['reminder_date']} {task['reminder_time']})"
        await update.message.reply_text(response)

# Function to view expired reminders for a user
async def view_expired(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_expired_tasks = expired_tasks.get(user_id, [])

    if not user_expired_tasks:
        await update.message.reply_text("You don't have any expired reminders.")
    else:
        response = "Your expired reminders:\n"
        for i, task in enumerate(user_expired_tasks):
            response += f"\n{str(i + 1)}. {task['reminder_name']} - {task['reminder_description']} (Scheduled at: {task['reminder_date']} {task['reminder_time']})"
        await update.message.reply_text(response)

# Function to edit reminders
async def edit_reminders(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_tasks = tasks.get(user_id, [])

    if not user_tasks:
        await update.message.reply_text("You don't have any reminders to edit.")
        return

    keyboard = [[InlineKeyboardButton(f"{i+1}. {task['reminder_name']}", callback_data=f"edit_{i}")] for i, task in enumerate(user_tasks)]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Please select a reminder to edit:", reply_markup=reply_markup)

# Function to handle reminder selection for editing
async def handle_edit_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    task_index = int(query.data.split("_")[1])

    EDIT_TASK_INDEX[user_id] = task_index
    USER_TASK_STATE[user_id] = 'name'

    task = tasks[user_id][task_index]
    await query.edit_message_text(f"Editing reminder: {task['reminder_name']}. Please send me the new reminder name or /cancel to cancel editing.")

# Function to delete a reminder
async def delete_reminder(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_tasks = tasks.get(user_id, [])

    if not user_tasks:
        await update.message.reply_text("You don't have any reminders to delete.")
        return

    keyboard = [[InlineKeyboardButton(f"{i+1}. {task['reminder_name']}", callback_data=f"delete_{i}")] for i, task in enumerate(user_tasks)]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Please select a reminder to delete:", reply_markup=reply_markup)

# Function to handle reminder selection for deletion
async def handle_delete_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    task_index = int(query.data.split("_")[1])

    deleted_task = tasks[user_id].pop(task_index)

    # Remove the scheduled job if it exists
    if user_id in SCHEDULED_JOBS and task_index in SCHEDULED_JOBS[user_id]:
        SCHEDULED_JOBS[user_id][task_index].remove()
        del SCHEDULED_JOBS[user_id][task_index]

    await query.edit_message_text(f"Reminder '{deleted_task['reminder_name']}' has been deleted.")

# Main function to set up the bot
def main():
    # Create an application with the bot's token
    application = Application.builder().token("8006841824:AAF4UPmaugdO3J4jsBOEA8bHAX4KV8FGHMc").build()  # Replace with your bot token

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_reminder", add_reminder))
    application.add_handler(CommandHandler("view_reminders", view_reminders))
    application.add_handler(CommandHandler("view_expired", view_expired))
    application.add_handler(CommandHandler("edit_reminders", edit_reminders))
    application.add_handler(CommandHandler("delete_reminder", delete_reminder))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_edit_selection, pattern="^edit_"))
    application.add_handler(CallbackQueryHandler(handle_delete_selection, pattern="^delete_"))

    # Start the scheduler
    scheduler.start()

    # Start polling for new updates from Telegram
    application.run_polling()

if __name__ == '__main__':
    main()
