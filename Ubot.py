import discord
import string
import gspread
from google.oauth2.service_account import Credentials
from discord.ext import commands
import os, json, re, asyncio
from datetime import datetime, timedelta
import google.generativeai as genai
from dotenv import load_dotenv

#Load env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("GEMINI_API_KEY")
SERVICE_ACCOUNT_FILE = os.path.join(os.getcwd(), "logger.json")

#Discord client with intents
intents = discord.Intents.all()
client = commands.Bot(command_prefix="/", intents=intents)

#Google Sheets setup
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
gs_client = gspread.authorize(creds)

#Insider Program 2.0 Hub Sheet
SHEET_ID_IP2_HUB = "1ZOYfeYQYpMRNeM4sEvCZZBKwxSUeFAUZEOfnj0WEzCI"
summaries_sheet = gs_client.open_by_key(SHEET_ID_IP2_HUB).worksheet("Ubot Summaries")
contributions_sheet = gs_client.open_by_key(SHEET_ID_IP2_HUB).worksheet("Insider Contributions")

#User Interviews Sheet
SHEET_ID_IP3_USER_INTERVIEWS = "1HyxWL3w7RVQ1Rto9PYFs5FoJQHLs19e6SJsprsqo3zQ"
user_transcripts = gs_client.open_by_key(SHEET_ID_IP3_USER_INTERVIEWS).worksheet("User Transcripts")
interview_notes = gs_client.open_by_key(SHEET_ID_IP3_USER_INTERVIEWS).worksheet("NEW Interview Tracking")

#Dev Tracker Sheet
SHEET_ID_DEV = "15Ysw6xXSLZaRa_BP7cQH2CBeRxh7FMFvLEy3R9YQmd8"
dev_sheet = gs_client.open_by_key(SHEET_ID_DEV).worksheet("Bravos")

#Channels to ignore
IGNORE_CHANNELS = ["👋welcome👋", "🙋intros🙋", "🔊announcements🔊", "📌rules📌", "team-ubiq"]

#Returns all data in given sheet.
def fetch_sheet_data(sheet):
    return sheet.get_all_records()


def choose_sheet_to_open(command):
    text = command.lower()
    if ("interview" in text and "devtracker" in text) or ("interviews" in text and "devtracker" in text) or ("interview" in text and "dev tracker" in text) or ("interviews" in text and "dev tracker" in text):
        return interview_notes, dev_sheet
    elif "interview" or "interviews" in text:
        return interview_notes
    elif "dev tracker" or "devtracker"  in text:
        return dev_sheet
    else: return "Couldn't figure out which sheet to open"


# Returns interview notes for one given interviewee.
def extract_user_interview_notes(sheet, name: str) -> list[str]:
    headers = sheet.row_values(1)

    try:
        col_index = headers.index(name) + 1
    except ValueError:
        raise ValueError(f"Interview for {name} not found.")

    data = sheet.col_values(col_index)

    # Drop the header row and any blank cells
    entries = [cell for cell in data[1:] if cell.strip()]
    return entries


async def call_gemini(prompt):
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    try:
        resp = await asyncio.to_thread(model.generate_content, prompt)
        return resp.text.strip()
    except Exception as e:
        return f"Something went wrong: {e}"



async def run_command(command: str) -> str:
    # Simplify the command text
    translator = str.maketrans("", "", string.punctuation)
    clean = command.translate(translator).lower()
    clean_no_space = clean.replace(" ", "")

    # Detect which sheets are requested
    has_dev = "devtracker" in clean_no_space or "dev tracker" in clean
    has_intv = "interview" in clean or "interviews" in clean
    choice = choose_sheet_to_open(command)

    # Handle both Dev-Tracker and Interviews
    if has_dev and has_intv and isinstance(choice, tuple):
        intv_sheet, dev_sheet_choice = choice
        dev_data = fetch_sheet_data(dev_sheet_choice)
        intv_data = fetch_sheet_data(intv_sheet)

        prompt = (
            "Dev Tracker:\n"
            f"{json.dumps(dev_data, indent=2)}\n\n"
            "User Interviews:\n"
            f"{json.dumps(intv_data, indent=2)}\n\n"
            f"Question: {command}\n"
            "Please keep your answer under 2000 characters."
        )
        return await call_gemini(prompt)

    # 4) Single sheet logic. Must be a single Worksheet here
    if not isinstance(choice, tuple):
        sheet = choice  # type: ignore
        # echo for your logs (won’t reach Discord)
        print(f"Opened sheet: {sheet.title} (ID: {sheet.id})")


        headers = sheet.row_values(1)
        has_name = any(h.lower() in clean for h in headers)

        # Name-specific interview
        if has_intv and has_name:
            interviewee = next(
                (h for h in headers if h.lower() in clean),
                None
            )
            assert interviewee is not None

            notes = extract_user_interview_notes(sheet, interviewee)
            notes_str = "\n".join(notes)
            prompt = (
                f"{command}\n\n"
                f"{notes_str}\n\n"
                "Please keep your answer under 2000 characters."
            )
            return await call_gemini(prompt)

        # Only “interview”
        elif has_intv:
            interview_data = fetch_sheet_data(interview_notes)
            prompt = f"Interview data:{interview_data} '\n' Prompt: {command} KEEP YOUR RESPONSE UNDER 2000 CHARACTERS\n\n"
            return await call_gemini(prompt)

        # 4c) Dev tracker only
        elif has_dev:
            dev_data = fetch_sheet_data(sheet)
            prompt = (
                "Dev Tracker:\n"
                f"{json.dumps(dev_data, indent=2)}\n\n"
                f"Question: {command}\n"
                "Please keep your answer under 2000 characters."
            )
            return await call_gemini(prompt)

    # 5) Fallback for everything else
    return (
        "Sorry, I didn’t understand that command. "
    )


# Logging functions
def log_contributions(contributions):
    entries = []
    for entry in contributions:
        user = entry.get("username", "UnknownUser")
        contrib = str(entry.get("contribution", "")).strip()
        if not contrib or user.lower() == "null":
            continue
        entries.append([user, 1, contrib])
    if entries:
        contributions_sheet.append_rows(entries)

def log_summary(summary):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summaries_sheet.append_row([stamp, summary])

# AI helper
def prepare_prompt(messages, task="Analyze"):
    joined = "\n".join(f"User: {u} - Message: {m}" for u, m in messages)
    return f"""
{task} Discord messages and extract only meaningful contributions (bugs, feedback, feature requests, answers). Return
a concise summary of what the messages consist of.
Messages:
{joined}
"""     

async def generate_contribution_data(messages):
    if not messages:
        return {"contributions": []}
    prompt = prepare_prompt(messages)
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    try:
        resp = await asyncio.to_thread(model.generate_content, prompt)
        match = re.search(r"\{.*\}", resp.text, re.DOTALL)
        return json.loads(match.group()) if match else {"contributions": []}
    except Exception:
        return {"contributions": []}

# Collect messages since a given time
async def collect_messages(guild, after=None):
    msgs = []
    for channel in guild.text_channels:
        if channel.name in IGNORE_CHANNELS:
            continue
        params = {'limit': None}
        if after:
            params['after'] = after
        async for m in channel.history(**params):
            if not m.author.bot and m.content.strip():
                msgs.append((m.author.name, m.content))
    return msgs

# Summarize and post messages
async def summarize_and_post(guild, after=None):
    msgs = await collect_messages(guild, after=after)
    if not msgs:
        return
    # generate summary
    #print(msgs[0:])
    prompt = prepare_prompt(msgs, task="Summarize")
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    try:
        resp = await asyncio.to_thread(model.generate_content, prompt)
        summary = resp.text.strip()
    except Exception:
        summary = "❗️ Error generating summary; please try again later."
    log_summary(summary)
    chan = discord.utils.get(guild.text_channels, name="summary")
    if chan:
        header = "**📢 Daily Summary:**\n"
        buffer = 2000 - len(header)
        for i in range(0, len(summary), buffer):
            chunk = summary[i:i+buffer]
            prefix = header if i == 0 else ""
            await chan.send(f"{prefix}{chunk}")

# Scheduled daily at midnight
async def daily_summary_task():
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now()
        # next midnight
        target = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        wait = (target - now).total_seconds()
        await asyncio.sleep(wait)
        since = target - timedelta(days=1)
        for g in client.guilds:
            await summarize_and_post(g, after=since)

@client.command(name="summary")
async def summary_cmd(ctx):
    # Manual summary: past 24h
    since = datetime.now() - timedelta(days=1)
    await summarize_and_post(ctx.guild, after=since)
    await ctx.send("✅ Summary generated.")

@client.command(name="count_answers")
@commands.has_permissions(administrator=True)
async def count_answers(ctx, channel_name: str = "📊prompts-and-polls📊"):
    ch = discord.utils.get(ctx.guild.text_channels, name=channel_name)
    if not ch:
        return await ctx.send(f"❌ Channel `{channel_name}` not found.")
    msgs = []
    async for m in ch.history(limit=None, after=datetime.now()-timedelta(days=1)):
        if not m.author.bot and m.content.strip():
            msgs.append((m.author.name, m.content))
    data = await generate_contribution_data(msgs)
    total = len(data.get("contributions", []))
    await ctx.send(f"📊 Found **{total}** meaningful answers in `#{channel_name}`.")

@client.command(name="count_messages")
@commands.has_permissions(administrator=True)
async def count_messages(ctx, channel_name: str = "📊prompts-and-polls📊"):
    ch = discord.utils.get(ctx.guild.text_channels, name=channel_name)
    if not ch:
        return await ctx.send(f"❌ Channel `{channel_name}` not found.")
    cnt = 0
    async for m in ch.history(limit=None, after=datetime.now()-timedelta(days=1)):
        if m.author.name.lower() != "ubiq.world":
            cnt += 1
    await ctx.send(f"📊 Total messages in `#{channel_name}` (last 24h): **{cnt}**")

# Events
@client.event
async def on_ready():
    client.loop.create_task(daily_summary_task())
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_member_join(member):
    await member.create_dm()
    await member.dm_channel.send(f"Hi {member.name}, welcome!")

@client.event
async def on_message(message):
    if message.author == client.user or message.author.bot:
        return

    if (
            message.channel.name == "summary"
            and (
            "ubot" in message.content.lower()
            or "ubot," in message.content.lower()
    )
    ):
        # Choose which sheet to open, send sheet data along with prompt to gemini, output response.
        reply = await run_command(message.content)
        await message.channel.send(reply)
        return

    if message.author.name == "ubiq.world" and message.content.strip() != "/summary":
        return
    result = await generate_contribution_data([(message.author.name, message.content)])
    if result.get("contributions"):
        log_contributions(result["contributions"])
    await client.process_commands(message)

# Run bot
client.run(TOKEN)
