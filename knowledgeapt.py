from datetime import datetime
from bs4 import BeautifulSoup
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from time import process_time, sleep
import urllib.request
import argparse

import config as config

PARSER = argparse.ArgumentParser()
PARSER.add_argument("--slack", help="print the available slots information to the configured slack channel", action="store_true")
ARGS = PARSER.parse_args()

APPOINTMNET_URL_PREFIX = "https://telegov.njportal.com"

TYPE_CODES = {
  "KNOWLEDGE TESTING": 17
}

MVC_LOCATION_CODES = {
  "KNOWLEDGE TESTING": {
    "PATERSON": 250,
    "LODI": 244,
    "WAYNE": 248,
    "NORTH BERGEN": 247,
    "NEWARK": 246,
    "BAYONNE": 233,
    "RAHWAY": 252,
    "EDISON": 240
  }
}

APPOINTMENT_TEMPLATE_URL = "https://telegov.njportal.com/njmvc/AppointmentWizard/{type_code}/{location_code}"

SLACK_CLIENT = WebClient(token=config.SLACK_BOT_TOKEN) if ARGS.slack else None

def _get_config_info():
  info = {}
  type_candidates = list(TYPE_CODES.items())
  for type, type_code in type_candidates:
    if type not in MVC_LOCATION_CODES:
      continue
    type_location_candidates = list(MVC_LOCATION_CODES[type].items())
    info[(type, type_code)] = type_location_candidates
  # print(info)
  return info


def _monitor_appointments(user_config_info):
  available_slots = {}
  for (type, type_code), location_candidates in user_config_info.items():
    for location_name, location_code in location_candidates:
      timeslot_url = APPOINTMENT_TEMPLATE_URL.format(
        type_code=type_code, location_code=location_code)

      request = urllib.request.Request(timeslot_url)
      try:
        response = urllib.request.urlopen(request)
      except:
        print("Failed to request {}, skipping".format(timeslot_url))
        continue

      result_html = response.read().decode("utf8")
      soup = BeautifulSoup(result_html, "html.parser")
      timeslots_container = soup.find(id="timeslots")
      if not timeslots_container:
        message = "Failed to find timeslots container while requesting {}, probably the MVC appointment system is down, waiting for 30 minutes to continue trying".format(timeslot_url)
        print(message)
        _send_slack_message(message)
        sleep(5)
        continue
      available_timeslots = timeslots_container.findChildren("a", recursive=False, href=True)
      if available_timeslots:
        for timeslot in available_timeslots:
          url = APPOINTMNET_URL_PREFIX + timeslot["href"]
          time = url.split("/")[-1]
          time_string = "0" + time[0] + ":" + time[1:] + "AM" if len(time) == 3 else time[0:2] + ":" + time[2:] + ("PM" if int(time[0:2]) >= 12 else "AM")
          available_slots[url] = {"type": type, "location": location_name, "url": url, "date": url.split("/")[-2], "time": time_string}
  return available_slots


def _send_slack_message(message):
  try:
    SLACK_CLIENT.chat_postMessage(channel=config.SLACK_CHANNEL_ID_KNOWLEDGE, text=message)
  except SlackApiError as e:
    print("Failed to communicate with Slack: {}".format(e.response['error']))


def _log_available_timeslots(new_slots, daily_slot_count):
  new_messages = []
  type_count = {}
  for url, detail in sorted(list(new_slots.items())):
    type = detail["type"]
    type_count[type] = type_count.get(type, 0) + 1
    new_messages.append("{} Appointment Slot #{}:\n\tlink: <{}|URL>,\n\tdate: {},\n\ttime: {}\n\tlocation: {}".format(
    type, type_count[type] + daily_slot_count.get(type, 0), url, detail["date"], detail["time"], detail["location"]))
  abridged_message = "\n\n------ \n *New appointment timeslots found!!!*\n------\n\n{}".format(",\n".join(new_messages))
  if ARGS.slack:
    _send_slack_message(abridged_message)
  else:
    print(abridged_message)
  return type_count


if __name__ == "__main__":
  config_info = _get_config_info()
  former_date = datetime.today().strftime("%Y-%m-%d")
  daily_found_urls = set()
  slot_count = {}
  while True:
    available_slots = _monitor_appointments(config_info)
    urls = set(available_slots.keys())
    new_urls = urls.difference(daily_found_urls)
    daily_found_urls = daily_found_urls.union(urls)
    if len(new_urls) > 0:
      new_slots = {url: available_slots[url] for url in new_urls}
      new_count = _log_available_timeslots(new_slots, slot_count)
      for type, count in new_count.items():
        slot_count[type] = slot_count.get(type, 0) + count
    sleep(5)
    current_date = datetime.today().strftime("%Y-%m-%d")
    if current_date != former_date:
      print("Passing one day, resetting the daily found urls and slot count...")
      former_date = current_date
      daily_found_urls.clear()
      slot_count.clear()