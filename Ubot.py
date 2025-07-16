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

#User Interviews Sheet (NO LONGER NEEDED, USING TRANSCRIPT FILE INSTEAD)
#SHEET_ID_IP3_USER_INTERVIEWS = "1HyxWL3w7RVQ1Rto9PYFs5FoJQHLs19e6SJsprsqo3zQ"
#user_transcripts = gs_client.open_by_key(SHEET_ID_IP3_USER_INTERVIEWS).worksheet("User Transcripts")
#interview_notes = gs_client.open_by_key(SHEET_ID_IP3_USER_INTERVIEWS).worksheet("NEW Interview Tracking")
TRANSCRIPTS_FILE=os.path.join(
    os.path.dirname(__file__),
    "transcripts",
    "ALL_OTTER_TRANSCRIPTS_noblanks.txt"
)


#Dev Tracker Sheet
SHEET_ID_DEV = "15Ysw6xXSLZaRa_BP7cQH2CBeRxh7FMFvLEy3R9YQmd8"
dev_sheet = gs_client.open_by_key(SHEET_ID_DEV).worksheet("Bravos")

#Product Master SHeet
SHEET_ID_PRODUCT_MASTER = "1Z0DfNptoMW1R_s19aYnHRhacQv1sUZd5yopi3p2EDZE"
product_master_sheet = gs_client.open_by_key(SHEET_ID_PRODUCT_MASTER).worksheet("MASTER Product Roadmap ")

#Channels to ignore
IGNORE_CHANNELS = ["👋welcome👋", "🙋intros🙋", "🔊announcements🔊", "📌rules📌", "team-ubiq"]


MAX_DISCORD_MSG = 2000

async def send_long(channel, content: str):
    for i in range(0, len(content), MAX_DISCORD_MSG):
        await channel.send(content[i : i + MAX_DISCORD_MSG])


def load_all_transcripts() -> str:
    with open(TRANSCRIPTS_FILE, "r", encoding="utf-8") as f:
        return f.read()


#Returns all data in given sheet.
def fetch_sheet_data(sheet):
    records = sheet.get_all_records()
    print(f"Loaded {sheet.title} With {len(records)} rows:")
    # for r in records:
    #     print(r)
    return records

    
def choose_sheet_to_open(command):
 text = command.lower()
 # Product Master, Interviews, AND Dev Tracker query
 if ("interview" in text or "interviews" in text) and ("devtracker" in text or "dev tracker" in text) and ("productmaster" in text or "product master" in text):
     return load_all_transcripts(), dev_sheet, product_master_sheet
 #Discord
 elif ("discord" in text):
     return None

 #Interview and Dev Tracker query
 elif ("interview" in text or "interviews" in text) and ("devtracker" in text or "dev tracker" in text):
     return load_all_transcripts(), dev_sheet
 #Interview and Product Master query
 elif ("interview" in text or "interviews" in text) and ("productmaster" in text or "product master" in text):
     return load_all_transcripts(), product_master_sheet
 #Product Master and Dev Tracker query
 elif ("product master" in text or "productmaster" in text) and ("devtracker" in text or "dev tracker" in text):
     return product_master_sheet, dev_sheet
 #Pure interviews
 elif "interview" in text or "interviews" in text:
     return load_all_transcripts()
 #Pure dev-tracker
 elif "devtracker" in text or "dev tracker" in text:
     return dev_sheet
 #Pure product master
 elif "product master" in text or "master" in text or "product" in text:
     return product_master_sheet
 else:
     return "Couldn't figure out which sheet to open"



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



async def run_command(command: str, guild: discord.Guild) -> str:
    # Simplify the command text
    translator = str.maketrans("", "", string.punctuation)
    clean = command.translate(translator).lower()
    clean_no_space = clean.replace(" ", "")

    # Detect which sheets are requested
    has_dev = "devtracker" in clean_no_space or "dev tracker" in clean
    has_intv = "interview" in clean or "interviews" in clean
    has_pmaster = "product master" in clean or "master" in clean or "product" in clean
    has_discord = "discord" in clean
    choice = choose_sheet_to_open(command)

    #Check if choice was the transcript file.
    if isinstance(choice, str):
        # print(f"TRANSCRIPT: {choice}")
        print("Analyzing Interview Transcripts")
        prompt = (
            f"All Interview Transcripts: {choice}\n"
            f"Prompt: {command}\n"
            ""
        )
       # print(prompt)
        return await call_gemini(prompt)


    # Dev Tracker + Interviews + Product Master case
    if has_dev and has_intv and has_pmaster \
            and isinstance(choice, tuple) and len(choice) == 3:
        first, second, third = choice

        # 1) Extract the transcript text
        transcripts = next(
            (x for x in (first, second, third) if isinstance(x, str)),
            ""
        )

        # 2) The remaining two items are your sheets
        sheets = [x for x in (first, second, third) if not isinstance(x, str)]
        dev_ws, pm_ws = sheets

        # 3) Fetch data only from real Worksheet objects
        dev_data = fetch_sheet_data(dev_ws)
        pm_data = fetch_sheet_data(pm_ws)

        # 4) Build the combined prompt
        prompt = (
            "Interview Transcripts:\n\n"
            f"{transcripts}\n\n"
            "Dev Tracker Data:\n"
            f"{json.dumps(dev_data, indent=2)}\n\n"
            "Product Master Data:\n"
            f"{json.dumps(pm_data, indent=2)}\n\n"
            f"Question: {command}\n"
            "Please answer using only the content above."
        )

        return await call_gemini(prompt)

    if isinstance(choice, tuple) and len(choice) == 2:
        #Find out which is the transcript.txt vs. a google sheet.
        first, second = choice

        if isinstance(first, str):
            transcripts = first
            sheet = second
        else:
            transcripts = second
            sheet = first
        sheet_data = fetch_sheet_data(sheet)
        prompt = (
            "Interview Transcripts:\n\n"
            f"{transcripts}\n\n"
            f"{sheet.title} Data:\n{json.dumps(sheet_data, indent=2)}\n\n"
            f"Question: {command}\n"
            "Please answer using only the content above."
        )
        return await call_gemini(prompt)

    if choice is None:
        print("Analyzing Discord Messages")

    # Single sheet logic. Must be a single Worksheet here
    if not isinstance(choice, tuple) and choice is not None:
        sheet = choice  # type: ignore
        # Debugging log
        print(f"Opened sheet: {sheet.title} (ID: {sheet.id})")


        headers = sheet.row_values(1)
        has_name = any(h.lower() in clean for h in headers)

        # Name specific interview command
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
                "Please keep your answer under 2000 characters and no less than 1000 characters, but be as detailed and through as possible."
            )
            return await call_gemini(prompt)


        # Dev tracker only
        elif has_dev:
            dev_data = fetch_sheet_data(sheet)
            prompt = (
                "Dev Tracker:\n"
                f"{json.dumps(dev_data, indent=2)}\n\n"
                f"Question: {command}\n"
                "Please keep your answer under 2000 characters and no less than 1000 characters, but be as detailed and through as possible."
            )
            return await call_gemini(prompt)
        # Product Master Query
        elif has_pmaster:
            pmaster_data = fetch_sheet_data(product_master_sheet)
            prompt = (
                "Product Master:\n"
                f"{json.dumps(pmaster_data, indent=2)}\n\n"
                f"Question: {command}\n"
                "Please keep your answer under 2000 characters and no less than 1000 characters, but be as detailed and through as possible."
            )
            return await call_gemini(prompt)

    if has_discord:
        messages = await collect_messages(guild)
        print(f"Found {len(messages)} Discord Messages")
        #print(messages)
        prompt = (
            "Discord Messages:\n"
            f"{json.dumps(messages, indent=2)}\n\n"
            f"Question: {command}\n"
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
        return await ctx.send(f" Channel `{channel_name}` not found.")
    msgs = []
    async for m in ch.history(limit=None):
        if not m.author.bot and m.content.strip():
            msgs.append((m.author.name, m.content))
    data = await generate_contribution_data(msgs)
    total = len(data.get("contributions", []))
    await ctx.send(f"📊 Found **{total}** meaningful answers in `#{channel_name}`.")

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
    print(f"🚨 Bot triggered by message: '{message.content}' from {message.author.name}")


    if (
            message.channel.name == "summary"
            and (
            "ubot" in message.content.lower()
            or "ubot," in message.content.lower()
    )
    ):
        # Choose which sheet to open, send sheet data along with prompt to gemini, output response.
        reply = await run_command(message.content, message.guild)
        await send_long(message.channel, reply)
        return

    if message.author.name == "ubiq.world" and message.content.strip() != "/summary":
        return
    result = await generate_contribution_data([(message.author.name, message.content)])
    if result.get("contributions"):
        log_contributions(result["contributions"])
    await client.process_commands(message)

# Run bot
client.run(TOKEN)
