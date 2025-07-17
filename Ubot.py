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

#Interview Transcript File
TRANSCRIPTS_FILE=os.path.join(
    os.path.dirname(__file__),
    "transcripts",
    "ALL_OTTER_TRANSCRIPTS_noblanks.txt"
)

#Dev Tracker Sheet
SHEET_ID_DEV = "15Ysw6xXSLZaRa_BP7cQH2CBeRxh7FMFvLEy3R9YQmd8"
dev_sheet = gs_client.open_by_key(SHEET_ID_DEV).worksheet("Bravos")

#Product Master Sheet
SHEET_ID_PRODUCT_MASTER = "1Z0DfNptoMW1R_s19aYnHRhacQv1sUZd5yopi3p2EDZE"
product_master_sheet = gs_client.open_by_key(SHEET_ID_PRODUCT_MASTER).worksheet("MASTER Product Roadmap ")

#Channels to ignore
IGNORE_CHANNELS = ["👋welcome👋", "🙋intros🙋", "🔊announcements🔊", "📌rules📌", "team-ubiq"]

#Discord message buffer
MAX_DISCORD_MSG = 2000

#Send long messages in chunks of 2000
async def send_long(channel, content: str):
    for i in range(0, len(content), MAX_DISCORD_MSG):
        await channel.send(content[i : i + MAX_DISCORD_MSG])

#Load interview transcripts and return content
def load_all_transcripts() -> str:
    with open(TRANSCRIPTS_FILE, "r", encoding="utf-8") as f:
        return f.read()


#Returns all data in any given sheet.
def fetch_sheet_data(sheet):
    records = sheet.get_all_records()
    print(f"Loaded {sheet.title} With {len(records)} rows:")
    # for r in records:
    #     print(r)
    return records


# Returns interview notes for one given interviewee. (Not Yet Used)
def extract_user_interview_notes(sheet, name: str) -> list[str]:
    headers = sheet.row_values(1)

    try:
        col_index = headers.index(name) + 1
    except ValueError:
        raise ValueError(f"Interview for {name} not found.")

    data = sheet.col_values(col_index)

    # Drops the header row and any blank cells
    entries = [cell for cell in data[1:] if cell.strip()]
    return entries


#Call gemini API model
async def call_gemini(prompt):
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    try:
        resp = await asyncio.to_thread(model.generate_content, prompt)
        return resp.text.strip()
    except Exception as e:
        return f"Something went wrong: {e}"

#Formats all messages for better AI readability 'John Doe:' 'I really like pizza'
def format_messages(messages):
    return "\n".join(f"- {user}: {msg}" for user, msg in messages)

#Using trigger words, analyze command and figure out with data files we will need to access.
def pick_data_sources(command: str):
    text = command.lower()
    sources = []

    if "discord" in text:
        sources.append("discord")

    if "interview" in text or "transcript" in text:
        sources.append("transcripts")

    if "devtracker" in text or "dev tracker" in text:
        sources.append(dev_sheet)

    if "product master" in text or "productmaster" in text or "master product" in text:
        sources.append(product_master_sheet)

    if not sources:
        # No trigger words matched
        return None
    return sources

async def run_command(command: str, guild: discord.Guild) -> str:
    sources = pick_data_sources(command)
    if sources is None:
        return "You didn't include the any trigger words. Trigger words: \n ▸'Discord' for discord related prompts. \n ▸'Interview or Transcripts' for interview related prompts\n ▸'Devtracker or Dev tracker' for dev related prompts\n ▸'Product master or Productmaster' for product master related prompts"

    prompt_sections = [f"Question: {command}"]

    for src in sources:
        if src == "discord":
            msgs = await collect_messages(guild)
            text_block = "\n".join(f"- {u}: {m}" for u, m in msgs)
            prompt_sections.append(f"Discord Messages:\n{text_block}")

        elif src == "transcripts":
            print("Analyzing transcripts...")
            transcripts = load_all_transcripts()
            prompt_sections.append(f"User Interview Transcripts:\n{transcripts}")

        else:
            # src must be a Worksheet
            data = fetch_sheet_data(src)
            prompt_sections.append(f"{src.title} Data:\n{json.dumps(data, indent=2)}")

    # # Finally append the user’s question
    # prompt_sections.append(f"Question: {command}")

    # Join all sections with blank lines
    full_prompt = "\n\n".join(prompt_sections)
    print(f"🚨🚨Full Prompt:\n{full_prompt}")

    return await call_gemini(full_prompt)


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
async def collect_messages(guild, after=None, per_channel_limit=200):
    msgs = []
    for channel in guild.text_channels:
        if channel.name in IGNORE_CHANNELS:
            continue
        params = {'limit': per_channel_limit}
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
