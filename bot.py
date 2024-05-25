import discord
from discord.ext import commands
from collections import defaultdict
import re
import io
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import aiohttp
import logging
import sqlite3

# Use a dictionary to manage all configurations. The channel ID corresponds to the channel type name and type
CHANNEL_CONFIGS = {
    11451419198101: {"name_prefix": "GameRoom", "type": "public"},
    11451419198102: {"name_prefix": "RelaxRoom", "type": "public"},
    81019191145141: {"name_prefix": "PrivateRoom", "type": "private"},
    81019191145142: {"name_prefix": "PVP Room", "type": "public"}
}

# The bot will send a welcome message to this channel
WELCOME_CHANNEL_ID = 114514114514114514

# Background image for the welcome picture
BACKGROUND_IMAGE = "background.png"
# Text color for the welcome picture
TEXT_COLOR = (255, 255, 255)  # RGB
# Font path for the welcome picture
FONT_PATH = "simhei.ttf"
# Font size for the welcome picture
FONT_SIZE = 60
# Avatar size for the welcome picture
AVATAR_SIZE = (250, 250)
# Distance between the first line of text and the avatar
WELCOME_TEXT_1_DISTANCE = 20
# Distance between the second line of text and the first line of text
WELCOME_TEXT_2_DISTANCE = 5
# Text for the welcome message
WELCOME_TEXT = "Welcome to the server, {member.mention}! Have a great time here."
# Text for the welcome picture
WELCOME_TEXT_PICTURE_1 = "Welcome {user_name} to this server！"
WELCOME_TEXT_PICTURE_2 = "You are the No.{member_number} member!"

# Your bot token
TOKEN = 'Your_Token_Here'

# List of user IDs that the bot will ignore
IGNORE_USER_IDS = [1234567899786574, 1145141919810]

intents = discord.Intents.all()
intents.members = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Store information about temporary channels
temp_channels = defaultdict(dict)

# Configure the logging system
logging.basicConfig(level=logging.INFO, filename='bot.log', filemode='a',
                    format='%(asctime)s - %(levelname)s - %(message)s')


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.tree.add_cog(WelcomeCog(self))
        await self.tree.sync()  # Sync the commands


class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name='testwelcome')
    async def test_welcome(self, interaction: discord.Interaction):
        member = interaction.user
        member_count = member.guild.member_count
        avatar_bytes = await download_avatar(member.display_avatar.url)
        welcome_image = create_welcome_image(member.name, member_count, avatar_bytes)
        discord_file = discord.File(fp=welcome_image, filename='welcome_image.png')
        welcome_message = WELCOME_TEXT.format(member=member.name, count=member_count)
        await interaction.response.send_message(content=welcome_message, file=discord_file)
        logging.info("test welcome command executed.")


@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user.name}')
    for guild in bot.guilds:
        logging.info(f"\nBot connected to server {guild.name}\n")
        print(f"\nBot connected to server {guild.name}\n")
        await bot.change_presence(activity=discord.Game(name=f"Working in {guild.name}"))


@bot.event
async def on_voice_state_update(member, before, after):
    # PUBLIC_CHANNEL_ID_LIST Public channel
    # PRIVATE_CHANNEL_ID_LIST Private channel

    # Check if the user has joined a specific channel
    if after.channel and after.channel.id in CHANNEL_CONFIGS:
        config = CHANNEL_CONFIGS[after.channel.id]
        if config["type"] == "public":
            await handle_channel(member, after, config, public=True)
        elif config["type"] == "private":
            await handle_channel(member, after, config, public=False)

    # Check if a user has left a temporary channel
    if before.channel and before.channel.id in temp_channels:
        # If the channel now has no users
        if len(before.channel.members) == 0:
            # Delete the channel
            await before.channel.delete()
            # Remove the channel from the dictionary
            del temp_channels[before.channel.id]


async def handle_channel(member, after, config, public=True):
    category = after.channel.category
    temp_channel_name = f"{config['name_prefix']}-{member.display_name}"

    if public:  # public channel
        overwrites = {
            after.channel.guild.default_role: discord.PermissionOverwrite(view_channel=True),
            member: discord.PermissionOverwrite(manage_channels=True, view_channel=True, connect=True, speak=True)
        }
    else:  # private channel
        overwrites = {
            after.channel.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, manage_channels=True)
        }

    # Create a new voice channel
    temp_channel = await after.channel.guild.create_voice_channel(
        name=temp_channel_name, category=category, overwrites=overwrites)

    # Store the channel ID and the user ID in the dictionary
    temp_channels[temp_channel.id] = member.id

    # Move the user to the new channel
    await member.move_to(temp_channel)


@bot.listen('on_message')
async def on_message(message):
    # Avoid the bot responding to its own messages
    if message.author == bot.user:
        return

    # Check for a message that only has 6 characters and does not contain certain patterns
    # However, if it contains "flex" or "rank" (in either case), it is not ignored.
    if (len(message.content) == 6 and
            not re.search(r"[=＝一二三四五\s]", message.content) and
            not re.search(r"(?i)(flex|rank)", message.content)):
        # print(f"Ignore message: {message.content}")
        return  # Ignore the message

    # Check if the message contains a URL
    if re.search(r"https?:\/\/", message.content):
        return

    # Ignore messages from specific users
    if message.author.id in IGNORE_USER_IDS:
        return

    # Prefix:  match "缺"|"等"|"="|"＝"|"q"|"Q"
    # Subject: match numbers|"一" to "五" Chinese characters|"n""N"|"全世界"|"Wworld"
    # Exclude: not followed by"分"|"分钟"|"min"|"个钟"|"小时"
    pattern = r"(?:(缺|等|[=＝]|[Qq]))(?:(\d|[一二三四五]|[nN]|全世界|world|World))(?!(分|分钟|min|个钟|小时))"

    # Find all matches in the content
    matches = re.findall(pattern, message.content, re.IGNORECASE)

    # Filter valid matches
    valid_matches = []
    for match in matches:
        if not re.search(r'\d[A-Z]$', message.content, re.IGNORECASE):
            valid_matches.append(match)

    if valid_matches:
        logging.info(f'Detected content from {message.author}: {message.content}, Matches: {valid_matches}!')

        # Check if the user is in a voice channel
        if message.author.voice and message.author.voice.channel:
            # Remove illegal teaming behaviour by users
            remove_illegal_activity(str(message.author.id))
            try:
                vc_url = await message.author.voice.channel.create_invite(max_age=600)  # Link valid for 10 minutes
                reply_message = f"{vc_url}"
            except Exception as e:
                reply_message = "Error creating invite link, please check my permissions."
        else:
            # Recording of illegal teaming behaviour by users
            log_illegal_activity(str(message.author.id), message.content)
            reply_message = f'{message.author.mention}, it is forbidden to pull privately, please start a voice channel!'

        await message.reply(reply_message)
        # Ends after the first match is replied to, ensuring that the same message is not replied to repeatedly
        return

    # Process commands
    await bot.process_commands(message)


# Download the user's avatar
async def download_avatar(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            avatar_bytes = await response.read()
    return avatar_bytes


# Create a welcome image
def create_welcome_image(user_name, member_number, avatar_bytes):
    with Image.open("background.png") as background:
        background = background.convert("RGBA")
        # Convert byte data to image
        avatar_image = Image.open(io.BytesIO(avatar_bytes))
        avatar_image = avatar_image.resize(AVATAR_SIZE)

        # Create avatar mask for circular avatar
        mask = Image.new('L', AVATAR_SIZE, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + AVATAR_SIZE, fill=255)
        avatar_image.putalpha(mask)

        # Calculate position for the avatar (middle, a bit towards the top)
        bg_width, bg_height = background.size
        avatar_position = ((bg_width - AVATAR_SIZE[0]) // 2, (bg_height - AVATAR_SIZE[1]) // 3)
        background.paste(avatar_image, avatar_position, avatar_image)

        # Creating a draw object to draw text on a background image
        draw = ImageDraw.Draw(background)
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

        # First line of text
        text1 = WELCOME_TEXT_PICTURE_1.format(user_name=user_name)
        text1_width = draw.textlength(text1, font=font)
        text1_height = FONT_SIZE  # Assuming single line, this might need adjustment

        # Second line of text
        text2 = WELCOME_TEXT_PICTURE_2.format(member_number=member_number)
        text2_width = draw.textlength(text2, font=font)

        # Position for the first line of text, placed below the avatar with some space
        text1_x = (background.width - text1_width) // 2
        text1_y = avatar_position[1] + AVATAR_SIZE[1] + WELCOME_TEXT_1_DISTANCE  # pixels below the avatar

        # Position for the second line of text, placed below the first line
        text2_x = (background.width - text2_width) // 2
        text2_y = text1_y + text1_height + WELCOME_TEXT_2_DISTANCE  # pixels space between lines

        # Drawing the text
        draw.text((text1_x, text1_y), text1, fill=TEXT_COLOR, font=font)
        draw.text((text2_x, text2_y), text2, fill=TEXT_COLOR, font=font)

        # Convert to bytes
        final_buffer = io.BytesIO()
        background.save(final_buffer, "PNG")
        final_buffer.seek(0)

    return final_buffer


# Event to handle new members joining the server
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        # Get the member count for the welcome message
        member_count = member.guild.member_count
        avatar_bytes = await download_avatar(member.avatar.url)
        welcome_image = create_welcome_image(member.name, member_count, avatar_bytes)
        discord_file = discord.File(fp=welcome_image, filename='welcome_image.png')
        # Send the welcome message with text and the welcome image
        welcome_message = WELCOME_TEXT.format(member=member)
        await channel.send(welcome_message, file=discord_file)
        logging.info(f"Welcome message sent for {member.id}")


@bot.command(name='testwelcome')
async def test_welcome(ctx):
    member = ctx.author
    if ctx.channel.id == WELCOME_CHANNEL_ID:
        # Get the member count for the welcome message
        member_count = member.guild.member_count
        avatar_bytes = await download_avatar(member.avatar.url)
        welcome_image = create_welcome_image(member.name, member_count, avatar_bytes)
        discord_file = discord.File(fp=welcome_image, filename='welcome_image.png')
        # Send the welcome message with text and the welcome image
        welcome_message = WELCOME_TEXT.format(member=member)
        await ctx.send(content=welcome_message, file=discord_file)
        logging.info("test welcome command executed.")
    else:
        await ctx.send("Please use this command in the 'welcome' channel.")
        logging.info("welcome command executed in the wrong channel.")


def log_illegal_activity(user_id, message):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    now = datetime.now()
    formatted_now = now.strftime('%Y-%m-%d %H:%M:%S')  # 将 datetime 转换为字符串
    c.execute('INSERT INTO illegal_teaming (user_id, timestamp, message) VALUES (?, ?, ?)',
              (user_id, formatted_now, message))
    conn.commit()
    conn.close()


def remove_illegal_activity(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    threshold = datetime.now() - timedelta(minutes=5)
    formatted_threshold = threshold.strftime('%Y-%m-%d %H:%M:%S')  # 格式化时间为字符串
    c.execute('DELETE FROM illegal_teaming WHERE user_id = ? AND timestamp > ?', (user_id, formatted_threshold))
    conn.commit()
    conn.close()


def get_illegal_teaming_stats():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''
        SELECT user_id, COUNT(*) as count FROM illegal_teaming
        GROUP BY user_id
        ORDER BY count DESC
        LIMIT 20
    ''')
    results = c.fetchall()
    conn.close()
    return results


def get_users_with_min_records(min_records):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''
        SELECT user_id, COUNT(*) as count FROM illegal_teaming
        GROUP BY user_id
        HAVING COUNT(*) > ?
        ORDER BY count DESC
    ''', (min_records,))
    results = c.fetchall()
    conn.close()
    return results


@bot.command(name='check_illegal_teaming')
async def check_illegal_teaming(ctx):
    # Define the channel ID where the command can be executed
    allowed_channel_id = WELCOME_CHANNEL_ID

    # Check if the current command is executed in the allowed channel
    if ctx.channel.id != allowed_channel_id:
        await ctx.send("This command can only be used in specific channels.")
        return

    top_users = get_illegal_teaming_stats()
    if not top_users:
        await ctx.send("No illegal teaming records found.")
        return

    message = "Top 20 illegal teaming users:\n"
    for user_id, count in top_users:
        user = bot.get_user(int(user_id))
        if user:  # Check if the user is still in the server
            message += f"{user.mention} with {count} records.\n"
        else:
            message += f"User ID {user_id} with {count} records is not in the server anymore.\n"
    await ctx.send(message)


@bot.command(name='check_user_records')
async def check_user_records(ctx, x: int):
    # Define the channel ID where the command can be executed
    allowed_channel_id = WELCOME_CHANNEL_ID

    # Check if the current command is executed in the allowed channel
    if ctx.channel.id != allowed_channel_id:
        await ctx.send("This command can only be used in specific channels.")
        return

    top_users = get_users_with_min_records(x)
    if not top_users:
        await ctx.send(f"No users with more than {x} records found.")
        return

    message = f"Users with more than {x} records: \n"
    for user_id, count in top_users:
        user = bot.get_user(int(user_id))
        if user:
            message += f"{user.mention} with {count} records.\n"
        else:
            message += f"User ID {user_id} with {count} records is not in the server anymore.\n"
    await ctx.send(message)


@check_user_records.error
async def check_user_records_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        if error.param.name == 'x':
            await ctx.send("You need to specify a number. Usage: `!check_user_records <number>`")
    else:
        await ctx.send("An unexpected error occurred. Please try again.")


bot.run(TOKEN)
