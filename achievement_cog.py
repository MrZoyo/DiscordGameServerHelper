# Author: MrZoyo
# Version: 0.6.0
# Date: 2024-06-10
# ========================================
import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
from datetime import datetime, timezone
from discord.ui import Button, View
from illegal_team_act_cog import IllegalTeamActCog


class AchievementRefreshView(View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180.0)  # Specify the timeout directly here if needed
        self.bot = bot
        self.user_id = user_id
        self.message = None  # This will hold the reference to the message

        config = self.bot.get_cog('ConfigCog').config
        self.db_path = config['db_path']

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def format_page(self):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.cursor()
            await cursor.execute("SELECT * FROM achievements WHERE user_id = ?", (self.user_id,))
            user_record = await cursor.fetchone()

            if user_record is None:
                # This user is not in the database, so create a new record for them
                await cursor.execute(
                    "INSERT INTO achievements (user_id, message_count, reaction_count, time_spent) VALUES (?, ?, ?, ?)",
                    (self.user_id, 0, 0, 0))
                message_count, reaction_count, time_spent = 0, 0, 0
            else:
                _, message_count, reaction_count, time_spent = user_record

            await db.commit()

        # Load the achievements from the config.json file
        achievements = self.bot.get_cog('AchievementCog').achievements

        # Add the count for each achievement
        for achievement in achievements:
            if achievement['type'] == 'reaction':
                achievement['count'] = reaction_count
            elif achievement['type'] == 'message':
                achievement['count'] = message_count
            else:  # 'time_spent'
                achievement['count'] = time_spent / 60  # Convert seconds to minutes

        # Count the number of completed achievements
        completed_achievements = sum(1 for a in achievements if a["count"] >= a["threshold"])

        # Get the user's mention and name
        user = await self.bot.fetch_user(self.user_id)
        user_mention = user.mention
        user_name = user.name

        # Create an embed with the user's achievements
        config = self.bot.get_cog('ConfigCog').config
        title = config['achievements_page_title'].format(user_name=user_name)
        description = config['achievements_page_description'].format(user_mention=user_mention,
                                                                     completed_achievements=completed_achievements,
                                                                     total_achievements=len(achievements))
        achievements_finish_emoji = config['achievements_finish_emoji']
        achievements_incomplete_emoji = config['achievements_incomplete_emoji']

        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())

        for achievement in achievements:
            emoji = achievements_finish_emoji if achievement["count"] >= achievement[
                "threshold"] else achievements_incomplete_emoji
            progress = min(1, achievement["count"] / achievement["threshold"])
            progress_bar = f"{emoji} **{achievement['description']}** → `{int(achievement['count'])}/{int(achievement['threshold'])}`\n`{'█' * int(progress * 20)}{' ' * (20 - int(progress * 20))}` `{progress * 100:.2f}%`"
            embed.add_field(name=achievement["name"], value=progress_bar, inline=False)

        return embed


class ConfirmationView(View):
    def __init__(self, bot, member_id, reactions, messages, time_spent, operation):
        super().__init__(timeout=120.0)
        self.bot = bot
        self.member_id = member_id
        self.reactions = reactions
        self.messages = messages
        self.time_spent = time_spent
        self.operation = operation  # 'increase' or 'decrease'

        config = self.bot.get_cog('ConfigCog').config
        self.db_path = config['db_path']

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        self.stop()  # Optionally stop further interactions if desired
        await self.message.edit(content="**Timeout: No longer accepting interactions.**", view=self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Immediate feedback
        await interaction.response.edit_message(content="**Processing your request...**", view=None)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.cursor()
            await cursor.execute("SELECT * FROM achievements WHERE user_id = ?", (self.member_id,))
            user_record = await cursor.fetchone()

            if user_record is None:
                await cursor.execute(
                    "INSERT INTO achievements (user_id, message_count, reaction_count, time_spent) VALUES (?, ?, ?, ?)",
                    (self.member_id, 0, 0, 0))
            new_values = (self.messages, self.reactions, self.time_spent, self.member_id)
            if self.operation == 'increase':
                await cursor.execute(
                    "UPDATE achievements SET message_count = message_count + ?, reaction_count = reaction_count + ?, time_spent = time_spent + ? WHERE user_id = ?",
                    new_values)
            elif self.operation == 'decrease':
                await cursor.execute(
                    "UPDATE achievements SET message_count = message_count - ?, reaction_count = reaction_count - ?, time_spent = time_spent - ? WHERE user_id = ?",
                    new_values)
            await db.commit()

        await interaction.edit_original_response(content=f"**Operation {self.operation} complete!**", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="**Operation cancelled!**", view=self)


class AchievementRankingView(View):
    def __init__(self, bot):
        super().__init__(timeout=180.0)
        self.bot = bot
        self.message = None  # This will hold the reference to the message

        config = self.bot.get_cog('ConfigCog').config
        self.db_path = config['db_path']

    async def format_page(self):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.cursor()

            # Fetch the top 10 users for each category
            await cursor.execute("SELECT user_id, reaction_count FROM achievements ORDER BY reaction_count DESC LIMIT 10")
            top_reactions = await cursor.fetchall()
            await cursor.execute("SELECT user_id, message_count FROM achievements ORDER BY message_count DESC LIMIT 10")
            top_messages = await cursor.fetchall()
            await cursor.execute("SELECT user_id, time_spent FROM achievements ORDER BY time_spent DESC LIMIT 10")
            top_time_spent = await cursor.fetchall()

        # Map the types to the corresponding SQL query results
        top_users = {
            "reactions": top_reactions,
            "messages": top_messages,
            "time_spent": top_time_spent
        }

        # Define the emojis for the ranks
        config = self.bot.get_cog('ConfigCog').config
        rank_emojis = config['achievements_ranking_emoji']

        # Load the achievement_ranking
        achievements_ranking = config['achievements_ranking']

        # Create an embed with the rankings
        title = config['achievements_ranking_title']
        embed = discord.Embed(title=title, color=discord.Color.blue())

        for achievement in achievements_ranking:
            ranking = ""
            for i, (user_id, count) in enumerate(top_users[achievement["type"]]):
                user = await self.bot.fetch_user(user_id)
                if achievement["type"] == "time_spent":
                    count /= 60  # Convert seconds to minutes
                ranking += f"{rank_emojis[i]} {user.mention} - {int(count)}\n"
            embed.add_field(name=achievement["name"], value=ranking, inline=False)

        return embed


class AchievementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_state = {}  # To track the time users join a voice channel
        self.illegal_act_cog = IllegalTeamActCog(bot)

        config = self.bot.get_cog('ConfigCog').config
        self.db_path = config['db_path']
        self.achievements = config['achievements']

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.cursor()
            await cursor.execute("SELECT * FROM achievements WHERE user_id = ?", (message.author.id,))
            user = await cursor.fetchone()

            if user is None:
                # This user is not in the database, so create a new record for them
                await cursor.execute(
                    "INSERT INTO achievements (user_id, message_count, reaction_count, time_spent) VALUES (?, ?, ?, ?)",
                    (message.author.id, 1, 0, 0))
            else:
                # This user is in the database, so increment their message count
                await cursor.execute("UPDATE achievements SET message_count = message_count + 1 WHERE user_id = ?",
                                     (message.author.id,))

            await db.commit()

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.cursor()
            await cursor.execute("SELECT * FROM achievements WHERE user_id = ?", (user.id,))
            user_record = await cursor.fetchone()

            if user_record is None:
                # This user is not in the database, so create a new record for them
                await cursor.execute(
                    "INSERT INTO achievements (user_id, message_count, reaction_count, time_spent) VALUES (?, ?, ?, ?)",
                    (user.id, 0, 1, 0))
            else:
                # This user is in the database, so increment their reaction count
                await cursor.execute("UPDATE achievements SET reaction_count = reaction_count + 1 WHERE user_id = ?",
                                     (user.id,))

            await db.commit()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        current_time = datetime.now(timezone.utc)

        # When the member leaves a channel
        if before.channel is not None:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.cursor()
                # Retrieve the start time and channel ID from the database for the user
                await cursor.execute("SELECT start_time, channel_id FROM voice_channel_entries WHERE user_id = ?",
                                     (member.id,))
                entry = await cursor.fetchone()

                # Process time spent only if the user left the same channel they entered
                if entry and entry[1] == before.channel.id:
                    start_time = datetime.fromisoformat(entry[0])
                    time_spent = (current_time - start_time).total_seconds()

                    # Update or insert time spent in achievements
                    await cursor.execute("SELECT time_spent FROM achievements WHERE user_id = ?",
                                         (member.id,))
                    user_record = await cursor.fetchone()
                    if user_record:
                        await cursor.execute("UPDATE achievements SET time_spent = time_spent + ? WHERE user_id = ?",
                                             (time_spent, member.id))
                    else:
                        await cursor.execute("INSERT INTO achievements (user_id, time_spent) VALUES (?, ?)",
                                             (member.id, time_spent))

                    # Delete the entry from voice_channel_entries since the session is complete
                    await cursor.execute("DELETE FROM voice_channel_entries WHERE user_id = ? AND channel_id = ?",
                                         (member.id, before.channel.id))

                await db.commit()

        # Handle joining a new channel
        if after.channel is not None:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.cursor()
                # Record the new channel entry
                await cursor.execute(
                    "REPLACE INTO voice_channel_entries (user_id, channel_id, start_time) VALUES (?, ?, ?)",
                    (member.id, after.channel.id, current_time.isoformat()))
                await db.commit()

    @app_commands.command(
        name="achievements",
        description="Query the current progress of achievements"
    )
    @app_commands.describe(member="The member to query. Defaults to self if not provided")
    async def achievements(self, interaction: discord.Interaction, member: discord.Member = None):
        # Defer the interaction
        await interaction.response.defer()

        if member is None:
            member = interaction.user  # Default to the user who invoked the command

        view = AchievementRefreshView(self.bot, member.id)
        embed = await view.format_page()
        message = await interaction.edit_original_response(embeds=[embed], view=view)
        view.message = message

    @app_commands.command(
        name="increase_achievement",
        description="Increase the achievement progress of a member"
    )
    @app_commands.describe(
        member="The member whose achievement progress to increase",
        reactions="The number of reactions to increase",
        messages="The number of messages to increase",
        time_spent="The time spent on the server to increase (in seconds)"
    )
    async def increase_achievement_progress(self, interaction: discord.Interaction, member: discord.Member,
                                            reactions: int = 0,
                                            messages: int = 0, time_spent: int = 0):
        if not await self.illegal_act_cog.check_channel_validity(interaction):
            return

        await interaction.response.defer()  # Properly defer to handle possibly lengthy DB operations

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.cursor()
            await cursor.execute("SELECT * FROM achievements WHERE user_id = ?", (member.id,))
            user_record = await cursor.fetchone()

            if user_record is None:
                # This user is not in the database, so create a new empty record for them
                await cursor.execute(
                    "INSERT INTO achievements (user_id, message_count, reaction_count, time_spent) VALUES (?, ?, ?, ?)",
                    (member.id, 0, 0, 0))
            await db.commit()

            # Create a confirmation view and send it with an embed
            view = ConfirmationView(self.bot, member.id, reactions, messages, time_spent, 'increase')
            embed = discord.Embed(title="Increase Achievement Progress",
                                  description=f"You will increase the achievement progress of {member.mention}.",
                                  color=discord.Color.blue())
            embed.add_field(name="Reactions to Add", value=str(reactions), inline=True)
            embed.add_field(name="Messages to Add", value=str(messages), inline=True)
            embed.add_field(name="Time to Add (seconds)", value=str(time_spent), inline=True)
            await interaction.edit_original_response(embed=embed, view=view)

    @app_commands.command(
        name="decrease_achievement",
        description="Decrease the achievement progress of a member"
    )
    @app_commands.describe(
        member="The member whose achievement progress to decrease",
        reactions="The number of reactions to decrease",
        messages="The number of messages to decrease",
        time_spent="The time spent on the server to decrease (in seconds)"
    )
    async def decrease_achievement_progress(self, interaction: discord.Interaction, member: discord.Member,
                                            reactions: int = 0,
                                            messages: int = 0, time_spent: int = 0):
        if not await self.illegal_act_cog.check_channel_validity(interaction):
            return

        await interaction.response.defer()  # Defer interaction for database operations

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.cursor()
            await cursor.execute("SELECT * FROM achievements WHERE user_id = ?", (member.id,))
            user_record = await cursor.fetchone()

            if user_record is None:
                # This user is not in the database, so create a new empty record for them
                await cursor.execute(
                    "INSERT INTO achievements (user_id, message_count, reaction_count, time_spent) VALUES (?, ?, ?, ?)",
                    (member.id, 0, 0, 0))
            await db.commit()

            # Create a confirmation view and send it with an embed
            view = ConfirmationView(self.bot, member.id, reactions, messages, time_spent, 'decrease')
            embed = discord.Embed(title="Decrease Achievement Progress",
                                  description=f"You will decrease the achievement progress of {member.mention}.",
                                  color=discord.Color.blue())
            embed.add_field(name="Reactions to Subtract", value=str(reactions), inline=True)
            embed.add_field(name="Messages to Subtract", value=str(messages), inline=True)
            embed.add_field(name="Time to Subtract (seconds)", value=str(time_spent), inline=True)
            await interaction.edit_original_response(embed=embed, view=view)

    @app_commands.command(
        name="achievement_ranking",
        description="Display the achievement rankings"
    )
    async def achievement_ranking(self, interaction: discord.Interaction):
        # Defer the interaction
        await interaction.response.defer()

        view = AchievementRankingView(self.bot)
        embed = await view.format_page()
        # Correct method to edit the message after deferring
        await interaction.edit_original_response(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.cursor()
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS achievements (
                    user_id INTEGER PRIMARY KEY,
                    message_count INTEGER DEFAULT 0,
                    reaction_count INTEGER DEFAULT 0,
                    time_spent INTEGER DEFAULT 0
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS voice_channel_entries (
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    PRIMARY KEY (user_id, channel_id)
                )
            """)

            # Fetch all the users that have been logged in voice_channel_entries
            await cursor.execute("SELECT user_id, channel_id FROM voice_channel_entries")
            entries = await cursor.fetchall()

            for user_id, channel_id in entries:
                member = None
                for guild in self.bot.guilds:
                    member = guild.get_member(user_id)
                    if member is not None:
                        break
                if member is None or member.voice is None or member.voice.channel.id != channel_id:
                    # The member is no longer on the server or is currently in a different room
                    await cursor.execute("DELETE FROM voice_channel_entries WHERE user_id = ? AND channel_id = ?",
                                         (user_id, channel_id))
            await db.commit()