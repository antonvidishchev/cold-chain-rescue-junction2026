import azure.functions as func

from app.cloud.api import app as api
from app.cloud.notifications import process_notifications
from app.cloud.service import check_offline
from app.cloud.store import get_store
from app.cloud.worker import image_id_from_message, mark_poison, process_image, recover_images

# Reads are public; the API validates separate device and operator keys on protected routes.
app = func.AsgiFunctionApp(app=api, http_auth_level=func.AuthLevel.ANONYMOUS)


@app.queue_trigger(arg_name="message", queue_name="%IMAGE_QUEUE_NAME%", connection="ImageStorage")
def analyze_camera_image(message: func.QueueMessage):
    process_image(image_id_from_message(message.get_body()))


@app.queue_trigger(arg_name="message", queue_name="%IMAGE_QUEUE_NAME%-poison", connection="ImageStorage")
def failed_camera_image(message: func.QueueMessage):
    mark_poison(image_id_from_message(message.get_body()))


@app.timer_trigger(arg_name="timer", schedule="0 * * * * *", use_monitor=True)
def monitor_devices(timer: func.TimerRequest):
    check_offline(get_store())


@app.timer_trigger(arg_name="timer", schedule="15 * * * * *", use_monitor=True)
def deliver_notifications(timer: func.TimerRequest):
    process_notifications()


@app.timer_trigger(arg_name="timer", schedule="0 */5 * * * *", use_monitor=True)
def recover_image_jobs(timer: func.TimerRequest):
    recover_images()
