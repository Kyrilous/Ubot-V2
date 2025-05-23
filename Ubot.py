import discord
import gspread
from google.oauth2.service_account import Credentials
from discord.ext import commands
import os
import json
import re
import asyncio
from datetime import datetime, timedelta
import google.generativeai as genai
from dotenv import load_dotenv
from google.generativeai import types

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("GEMINI_API_KEY")
SERVICE_ACCOUNT_FILE = os.path.join(os.getcwd(), "logger.json")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

client = commands.Bot(command_prefix="/", intents=intents)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
gs_client = gspread.authorize(creds)

SHEET_ID = "1ZOYfeYQYpMRNeM4sEvCZZBKwxSUeFAUZEOfnj0WEzCI"
ubot_summaries = gs_client.open_by_key(SHEET_ID).worksheet("Ubot Summaries")
insider_contributions = gs_client.open_by_key(SHEET_ID).worksheet("Insider Contributions")

# Global lists for channels to ignore during message collection/processing
COLLECT_EXCLUDED_CHANNELS = ["summary", "👋welcome👋", "🙋intros🙋", "🔊announcements🔊", "📌rules📌"]
MESSAGE_IGNORE_CHANNELS = ["👋welcome👋", "🙋intros🙋", "🔊announcements🔊", "📌rules📌", "team-ubiq"]

def log_user_contribution(contributions):
  """
  Logs user contributions in the Google Sheet and prints debug info.
  """
  sheet_name = "Insider Contributions"
  print(f"📝 Attempting to log contributions to Google Sheet: {SHEET_ID} → Worksheet: {sheet_name}")
  try:
    sheet = gs_client.open_by_key(SHEET_ID).worksheet(sheet_name)
    print("📝 log_user_contribution() called!")
    print("📝 Contributions received:", contributions)
    new_entries = []
    for entry in contributions:
      username = entry.get("username", "UnknownUser")
      contribution_summary = entry.get("contribution", "No contribution provided.")
      if contribution_summary.strip() == "No contribution provided.":
        continue
      if not username or username.lower() == "null":
        username = "UnknownUser"
      if not isinstance(contribution_summary, str):
        contribution_summary = str(contribution_summary)
      new_entries.append([username, 1, contribution_summary])
    if not new_entries:
      print("⚠️ No valid contributions found to log. Debugging AI output...")
      print("📝 Raw Contributions Received:", contributions)
      return
    print("📝 Final Entries to Log:", new_entries)
    sheet.append_rows(new_entries)
    print(f"✅ Successfully logged {len(new_entries)} contributions to '{sheet_name}' in Google Sheets (ID: {SHEET_ID}).")
  except gspread.exceptions.WorksheetNotFound:
    print(f"❌ Error: Worksheet '{sheet_name}' not found in Google Sheets (ID: {SHEET_ID}). Check if the name is correct.")
  except Exception as e:
    print(f"❌ Error logging contributions to Google Sheets (ID: {SHEET_ID}): {e}")

async def analyze_contributions(messages):
  """
  Uses Gemini AI to determine which messages are meaningful contributions.
  Returns a dictionary with usernames and their contributions.
  """
  print("DEBUG: Messages received in analyze_contributions:", messages)
  if not isinstance(messages, list):
    raise ValueError("Messages must be a list!")
  for m in messages:
    if not isinstance(m, tuple) or len(m) != 2:
      raise ValueError(f"Invalid message format: {m}. Expected a tuple (username, message).")
  formatted_messages = "\n".join(
      f"User: {username} - Message: {msg}" if isinstance(msg, str) and msg.strip() else "Unknown message"
      for username, msg in messages
  )
  print("🔍 Formatted Messages for AI Analysis:\n", formatted_messages)
  prompt = f"""
    You are analyzing Discord messages from an insider program for an app called Ubiq.
    
    **Your task: Extract ONLY meaningful contributions related to the app. Ignore everything else.**
    
    🚨 **Strict Filtering Rules:**
    - ✅ **Contributions Include:**
      - Bug reports (e.g., "I found a bug where the app crashes when logging in.")
      - Feedback on the Ubiq app (e.g., "The 3D map makes navigation much easier.")
      - ANY ANSWER RELATED TO A PROMPT QUESTION
      - Feature requests (e.g., "Can you add a dark mode?")
      - **Do NOT ignore well-written messages just because they do not explicitly mention 'bug' or 'feature'.**
      - Questions about the Ubiq app (e.g., "How do I reset my password?")
      
    **HERE IS A LIST OF ALL THE PROMPTS ASKED TO USERS, IF YOU SEE AN ANSWER TO ANY PROMPT, MARK IT AS CONTRIBUTION**: 
    "Prompt 8:
      Hey @everyone,
      Now we know your prefrence regarding the map, what about the interface and any problems you encounter?
      Which type of interface do you prefer?
      🌐 3D World and Spatial Stories
      📜 Traditional Feed UI
      🤷‍♂️ No preference
      What challenges do you face when using Ubiq's Spatial UI?"
      
      "Prompt 9:
      Hey @everyone!
      ❄️ What’s your favorite winter memory?
      We’d love to see it! Share a photo or story from your winter adventures and add a fun caption to go with it. Let’s remember those cold adventures together! ❄️📸"
      
      "Prompt 10:
      Hey Insiders! @everyone 👋
      We’d love to hear how you feel about using Ubiq and the value it brings to you. Your feedback helps us improve, so rate your experience on these two key questions:
      ⭐ How well do you understand how Ubiq works?
      (1️⃣ = Not at all | 5️⃣ = Completely)
      1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣
      ⭐ How well do you understand the value Ubiq provides to you?
      (1️⃣ = Not at all | 5️⃣ = Extremely valuable)
      1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣
      Feel free to drop any extra thoughts in the comments! ⬇️💡"
      
      "Prompt 11:
      Hey @everyone, thanks for all the valuable feedback so far! 🙌 Now, let’s talk about the app’s performance.
      🚀 Have you noticed any slow loading times or delays?
      (For example: Does it happen when opening the app, switching tabs, or loading specific features like your profile or settings?)
      ⚡ How would you rate the app’s overall performance?
      (1️⃣ = Very slow | 5️⃣ = Super fast)
      🔍 Are there specific areas that feel slower or less responsive?
      (Example: Does navigation between pages feel smooth, or do certain sections lag?)
      Answer the Polls & Drop your thoughts below! ⬇️💡"
      
      "Prompt 12:
      🚀 Insiders 1:1 Check-In! 🚀
      Hey @everyone, we’re scheduling 1:1 interviews with each Insider to hear your thoughts, feedback, and ideas on Ubiq. This is your chance to share your experience directly with us!
      📢 What’s working? What’s not? What do you want to see next?
      We want to hear it all! Book your 1:1 chat here: [Google Appointments Link] 📅
      Your insights are shaping the future of Ubiq—excited to connect with each of you! 🙌
      "
      
      "🌍 Prompt 13: Wanderlust Moments ✨
      Hey @everyone, have you ever seen a post on Ubiq that made you stop and think, "Where is that?" or even made you want to visit that place? 🌏
      👀 Has any post sparked your curiosity about a new destination?
      📍 What’s a place you’ve seen on Ubiq that you’d love to visit?
      Drop your thoughts below! Let’s explore the world through each other’s memories.. 🗺️✨"
      
      "Prompt 14:
      🚀 Spatial Stories: Refinement Time! 🎉
      Hey @everyone, a while back, we launched the new design of Spatial Stories, and now we’re working on making them even better! 🔧✨
      We’d love your feedback:
      1️⃣ What do you like about the current design?
      2️⃣ What could be improved to make them more engaging and seamless?
      3️⃣ Would you use them more if we added new features or made them exportable?
      Drop your thoughts below! Your insights will help shape the next iteration. Let’s refine this together! 🙌💡"
      
      "💬 Today’s Prompt: Create a spatial story of a hidden gem and explain why others should visit it. E.g. Restaurant, book store, bulba splace, park, etc"
      
      Slide into some DMs! If someone posted a hidden gem, whether it’s a 🔥 restaurant, a cozy bookstore, or a must-visit park. Hit them up and ask about it! Did the convo feel valuable? Would you actually check out their recommendation? Let us know how it goes! 🚀
      
      "IG vs. Ubiq? 🤔 Do you find Ubiq more interesting than IG? Does it actually help you feel closer to people or learn more about them?
      Location = Connection? 📍 Does seeing the location context in Spatial Stories make you feel closer to friends & family?
      Flat vs. Spatial? 🌍 Are Spatial Stories way more interesting than regular, flat posts? Be honest!
      Better for Sharing? 📸 When it comes to showing what you did, do you think "Spatial Stories" do it best?"
      
      "Hey @everyone!
      We’re working on some Ubiq swag and need your input! 🎉
      Check out the designs below and let us know what you think.
      For Shirt 2 and 4 they are the Baggy version of the design, do you prefer the baggy T-shirt look or a more fitted style?
      [Design images and poll details here]
      "
      
      DMs on Ubiq? 💬 Have you ever slid into someone’s DMs here? Do you find DMs valuable, or is there something missing?
    
    - ❌ **IGNORE:**
      - User introductions (e.g., "Hi, I'm Alex and I study Computer Science.")
      - IGNORE CONTRIBUTIONS MADE BY USER: ubiq.world, 
      - Personal stories (e.g., "I love gaming and cooking.")
      - Random conversation (e.g., "What's everyone's favorite movie?")
      - Any message that is NOT about the Ubiq app.
    
    **⚠️ IMPORTANT: Use the 'User' field from each message for the username.**
    
    ## **Strict JSON Format**
    ```json
    {{
      "contributions": [
        {{"username": "User1", "contribution": "Reported a bug where the app crashes on startup."}},
        {{"username": "User2", "contribution": "Suggested a feature for exporting data as CSV."}}
      ]
    }}
    ```
    
    Messages to analyze:
    {formatted_messages}
    """
  genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
  model = genai.GenerativeModel("gemini-1.5-pro-latest", generation_config={"temperature": 0.5})
  try:
    # Offload the blocking call to a separate thread
    response = await asyncio.to_thread(model.generate_content, prompt)
    await asyncio.sleep(0)
    response_text = response.text.strip()
    print("-----" + response_text)
    print("🔍 AI Raw Response:\n", response_text)
    response_text = response_text.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if not match:
      print("❌ AI response did not contain valid JSON. Returning empty dictionary.")
      return {"contributions": []}
    json_string = match.group(0).strip()
    print("🔍 Extracted JSON String:\n", json_string)
    try:
      structured_data = json.loads(json_string)
    except json.JSONDecodeError as e:
      print(f"❌ JSON parsing error: {e}")
      print("⚠️ Raw AI Response (Post Extraction):\n", json_string)
      return {"contributions": []}
    if "contributions" not in structured_data:
      print("❌ AI response is missing 'contributions' key. Returning empty dictionary.")
      print("⚠️ Parsed JSON:\n", json.dumps(structured_data, indent=2))
      return {"contributions": []}
    return structured_data
  except Exception as e:
    print(f"⚠️ Unexpected Error in analyze_contributions: {e}")
    return {"contributions": []}

def log_summary_to_sheet(summary):
  timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  ubot_summaries.append_row([timestamp, summary])

async def collect_recent_messages_for_guild(guild):
  formatted_messages = ""
  for channel in guild.text_channels:
    if channel.name in COLLECT_EXCLUDED_CHANNELS:
      continue
    messages_list = []
    async for message in channel.history(limit=100):
      if message.author.bot or not message.content.strip():
        continue
      messages_list.append((message.author.name, message.content))
    if messages_list:
      formatted_messages += f"\n#{channel.name}:\n" + "\n".join([f"User: {msg[0]} - Message: {msg[1]}" for msg in messages_list]) + "\n"
  if not formatted_messages.strip():
    print(f"❌ ERROR: No valid messages retrieved from guild {guild.name}.")
  else:
    print(f"✅ Messages successfully collected for guild {guild.name}.")
  return formatted_messages

async def generate(formatted_messages):
  if not formatted_messages.strip():
    print("❌ No valid messages to summarize.")
    return "No valid messages found."
  prompt_text = '''HERE IS A COLLECTION OF MESSAGES FROM AN INSIDER PROGRAM DISCORD FOR A SPATIAL MEDIA COMPANY. CHANNEL NAMES ARE MARKED WITH A "#".

YOUR TASK:
- ** DO NOT HALLUCINATE OR ASSUME ANY DETAILS JUST TO MEET THE CHARACTER LIMIT, ONLY PROVIDE FEEDBACK FROM THE GIVEN DATASET!**
- ** GET STRAIGHT TO THE POINT, THERE MUST BE BULLETPOINTS FOR EACH CHANNEL **
- ** MAKE SURE YOUR RESPONSE NEVER HAS '@everyone' IN IT.**
- **FOCUS HEAVILY ON CHANNEL: "🐞bugs-and-features🐞" AND "📊prompts-and-polls📊"
- **DISREGARD THE CHANNEL NAMED "summary"  COMPLETELY**
- ** AIM FOR CHARACTER COUNT NO LESS THAN 2500 AND NO MORE THAN 4000 **
- **Analyze each channel's discussions and extract key insights**.
- **Use Bullet Points When Summarizing Each Channel For Easier Readability**
- **Highlight important discussions** such as **bug reports, feature requests, feedback, and user concerns**.
- **Throughly analyze each channel in depth, there can be important messages in any given channel**.
- **Include specific details about problems users faced** (e.g., error messages, crashes, unexpected behavior).
- **Summarize feature requests with a short explanation of user needs**.
- **Identify recurring issues and trends**.
- **Summarize only important conversations—DO NOT include bot commands or irrelevant chat**.
- **Summarize clearly, grouping key points under each channel name**.
- **Ensure the response is detailed and informative, but under 4000 characters**.

HERE IS THE DATASET CONTAINING CHANNELS AND THEIR MESSAGES:''' + formatted_messages
  print("\n🔍 DEBUG: Data sent to AI for summary generation:\n")
  print(prompt_text[:2000])
  print("\n🔍 END OF DATA\n")
  genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
  model = genai.GenerativeModel("gemini-1.5-pro-latest")
  # Offload the blocking API call to a separate thread
  response = await asyncio.to_thread(model.generate_content, prompt_text)
  summary = response.text
  print(f"Summary Length: {len(summary)}")
  return summary

def split_message(message, limit=4000):
  """Splits a message into multiple parts for Discord's character limit."""
  return [message[i:i + limit] for i in range(0, len(message), limit)]

async def send_summary(summary_text, guild):
  summary_channel = discord.utils.get(guild.text_channels, name="summary")
  if summary_channel is None:
    print(f"❌ No summary channel found in guild {guild.name}.")
    return
  summary = f"**📢 Daily Summary:**\n{summary_text}"
  message_parts = split_message(summary, 2000)
  for part in message_parts:
    await summary_channel.send(part)

async def auto_generate_summary():
  await client.wait_until_ready()
  while not client.is_closed():
    now = datetime.now()
    target_time = now.replace(hour=1, minute=0, second=0, microsecond=0)  # 1AM
    if now > target_time:
      target_time += timedelta(days=1)
    wait_time = (target_time - now).total_seconds()
    print(f"Next summary scheduled at {target_time}. Waiting {wait_time / 3600:.2f} hours")
    await asyncio.sleep(wait_time)
    print("Generating daily summary for all guilds.")
    for guild in client.guilds:
      formatted_messages = await collect_recent_messages_for_guild(guild)
      if not formatted_messages.strip():
        continue
      summary_text = await generate(formatted_messages)
      log_summary_to_sheet(summary_text)
      await send_summary(summary_text, guild)

@client.command()
async def summary(ctx):
  print("✅ Summary command received!")
  guild = ctx.guild
  formatted_messages = await collect_recent_messages_for_guild(guild)
  if not formatted_messages.strip():
    await ctx.send("❌ No messages found to summarize.")
    return
  summary_text = await generate(formatted_messages)
  print(f"✅ Summary generated (length {len(summary_text)} characters).")
  log_summary_to_sheet(summary_text)
  await send_summary(summary_text, guild)
  print("✅ Summary sent to Discord.")
  await ctx.send("Summary has been generated and posted!")


@client.command(name="count_answers")
@commands.has_permissions(administrator=True)
async def count_answers(ctx, channel_name: str = "📊prompts-and-polls📊"):
  """
  Count only the messages in a channel that your AI deems 'meaningful contributions'
  (i.e. answers to prompts or polls), using your existing analyze_contributions().
  """
  # 1) find the channel
  channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
  if not channel:
    return await ctx.send(f"❌ Channel `{channel_name}` not found.")

  # 2) collect all non-bot, non-empty messages
  msgs = []
  async for m in channel.history(limit=None):
    if m.author.bot or not m.content.strip():
      continue
    msgs.append((m.author.name, m.content))

  if not msgs:
    return await ctx.send(f"ℹ️ No user messages found in `#{channel_name}`.")

  # 3) run your analyze_contributions AI filter on the batch
  result = await analyze_contributions(msgs)
  contributions = result.get("contributions", [])

  # 4) report back
  total = len(contributions)
  await ctx.send(f"📊 I found **{total}** meaningful answers in `#{channel_name}`.")


@client.event
async def on_member_join(member):
  await member.create_dm()
  await member.dm_channel.send(f'Hi {member.name}, welcome to the Ubiq insider program!')

@client.event
async def on_message(message):
  IGNORED_USERS = {"ubiq.world"}
  if message.author == client.user or message.author.bot:
    return
  if message.author.name in IGNORED_USERS:
    if message.content.strip() == "/summary":
      print(f"✅ Allowing /summary from ignored user: {message.author.name}")
      await client.process_commands(message)
      return
    else:
      print(f"❌ Ignoring message from {message.author.name}")
      return
  if message.channel.name in MESSAGE_IGNORE_CHANNELS:
    return
  print(f"✅ Processing message from {message.author.name} in guild {message.guild.name}: {message.content}")
  response = await analyze_contributions([(message.author.name, message.content)])
  if "contributions" in response:
    log_user_contribution(response["contributions"])
  await client.process_commands(message)

@client.command(name="count_messages")
@commands.has_permissions(administrator=True)
async def count_messages(ctx, channel_name: str = "📊prompts-and-polls📊"):
  """
  Count all messages in a channel (default: prompts-and-polls),
  excluding any sent by the 'ubiq.world' account.
  """
  # 1) look up the channel
  channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
  if not channel:
    return await ctx.send(f"❌ Channel `{channel_name}` not found.")

  # 2) iterate history and count everything except from ubiq.world
  count = 0
  async for msg in channel.history(limit=None):
    if msg.author.name.lower() == "ubiq.world":
      continue
    count += 1

  # 3) send result back into the same channel
  await ctx.send(f"📊 Total messages in `#{channel_name}` (excluding ubiq.world): **{count}**")


@client.event
async def on_ready():
  client.loop.create_task(auto_generate_summary())
  for guild in client.guilds:
    print(f"{client.user} has connected to: {guild.name} (id: {guild.id})")
    history_file = f"history_processed_{guild.id}.txt"
    if os.path.exists(history_file):
      print(f"✅ Historical messages already processed for {guild.name}. Skipping...")
    else:
      print(f"📜 Processing historical messages in batches for {guild.name}...")
      messages_per_channel = {}
      for channel in guild.text_channels:
        if channel.name in COLLECT_EXCLUDED_CHANNELS:
          continue
        messages_per_channel[channel.name] = []
        async for message in channel.history(limit=50):
          if message.author.bot:
            continue
          messages_per_channel[channel.name].append((message.author.name, message.content))
      batch_size = 150
      for channel_name, messages in messages_per_channel.items():
        print(f"\n📜 Processing messages from channel: {channel_name} in guild {guild.name}")
        for i in range(0, len(messages), batch_size):
          batch = messages[i:i + batch_size]
          total_batches = (len(messages) + batch_size - 1) // batch_size
          print(f"📌 Total number of batches being sent: {total_batches}")
          contribution_data = await analyze_contributions(batch)
          if "contributions" in contribution_data and contribution_data["contributions"]:
            log_user_contribution(contribution_data["contributions"])
          else:
            print("⚠️ No valid contributions detected from historical messages.")
          await asyncio.sleep(10)
      with open(history_file, "w") as f:
        f.write("done")
      print(f"✅ Historical messages processed for {guild.name}!")

# Have client just read token then shut down.
client.run(TOKEN)

