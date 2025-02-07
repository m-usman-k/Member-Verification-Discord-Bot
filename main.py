import discord, os, json
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


# Load verified role ID from config.json
def get_verified_role_id():
    if not os.path.exists("config.json"):
        return None
    with open("config.json", "r") as file:
        data = json.load(file)
    return data.get("allowed-role")


async def get_or_create_logs_channel(guild: discord.Guild):
    """Gets or creates a logs channel with admin-only permissions."""
    logs_channel = discord.utils.get(guild.text_channels, name="verification-logs")
    
    if logs_channel:
        return logs_channel

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    
    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    
    logs_channel = await guild.create_text_channel(name="verification-logs", overwrites=overwrites)
    return logs_channel


# Views for Verification Buttons
class VerificationView(discord.ui.View):
    def __init__(self, member: discord.Member, channel: discord.TextChannel, role: discord.Role):
        super().__init__(timeout=None)
        self.member = member
        self.channel = channel
        self.role = role

    async def check_admin(self, interaction: discord.Interaction):
        """Checks if the user interacting is an admin."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
            return False
        return True

    async def delete_role(self):
        """Deletes the temporary verification role."""
        try:
            await self.role.delete()
        except discord.Forbidden:
            print(f"Failed to delete role: {self.role.name}")

    async def send_log(self, guild: discord.Guild, message: str, color: discord.Color):
        """Sends an embed log message to the logs channel."""
        logs_channel = await get_or_create_logs_channel(guild)
        embed = discord.Embed(title="Verification Log", description=message, color=color)
        await logs_channel.send(embed=embed)

    @discord.ui.button(label="Allow", style=discord.ButtonStyle.green)
    async def allow(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_admin(interaction):
            return

        # Ask for confirmation
        confirm_view = discord.ui.View()
        confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.green)

        async def confirm_callback(interaction: discord.Interaction):
            verified_role_id = get_verified_role_id()
            if verified_role_id:
                verified_role = interaction.guild.get_role(verified_role_id)
                if verified_role:
                    await self.member.add_roles(verified_role)

            await self.member.remove_roles(self.role)  # Remove temp role
            await self.delete_role()  # Delete the temp role
            await self.send_log(interaction.guild, f"{self.member.mention} has been **verified** by {interaction.user.mention}.", discord.Color.green())
            await interaction.response.send_message(f"{self.member.mention} has been verified!", ephemeral=True)
            await self.channel.delete()  # Delete the ticket

        confirm_button.callback = confirm_callback
        confirm_view.add_item(confirm_button)

        await interaction.response.send_message("Are you sure you want to verify this user?", view=confirm_view, ephemeral=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_admin(interaction):
            return

        # Ask for confirmation
        confirm_view = discord.ui.View()
        confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.red)

        async def confirm_callback(interaction: discord.Interaction):
            await self.delete_role()  # Delete temp role
            await self.member.kick(reason="Verification Denied")  # Kick the user
            await self.send_log(interaction.guild, f"{self.member.mention} was **denied verification** and removed by {interaction.user.mention}.", discord.Color.red())
            await interaction.response.send_message(f"{self.member.mention} has been removed.", ephemeral=True)
            await self.channel.delete()  # Delete the ticket

        confirm_button.callback = confirm_callback
        confirm_view.add_item(confirm_button)

        await interaction.response.send_message("Are you sure you want to deny this user?", view=confirm_view, ephemeral=True)


# Event when a new member joins
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot is ready as {bot.user}.")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild

    # Check if category exists, if not create it
    category = discord.utils.get(guild.categories, name="VERIFICATION OPEN")
    if not category:
        category = await guild.create_category("VERIFICATION OPEN")

    # Create a role with the member's ID
    role_name = str(member.id)
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name)

    # Set permissions for the new ticket channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),  # Hide from everyone
        role: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),  # Allow the user
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),  # Allow the user
        guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True),  # Allow the bot
    }

    # Create the private ticket channel
    channel = await guild.create_text_channel(name=f"ticket-{member.id}", category=category, overwrites=overwrites)

    # Assign the role to the user
    await member.add_roles(role)

    # Send embed with verification buttons
    embed = discord.Embed(title="Verification", description=f"Please verify yourself, {member.mention}.")
    await channel.send(embed=embed, view=VerificationView(member, channel, role))

    # Log the new join
    logs_channel = await get_or_create_logs_channel(guild)
    join_embed = discord.Embed(title="New Member Joined", description=f"{member.mention} has joined and is waiting for verification.", color=discord.Color.blue())
    await logs_channel.send(embed=join_embed)


# Command to set the verified role
@bot.tree.command(name="set-verified-role", description="Set the role that will be given to verified members.")
async def set_verified_role(interaction: discord.Interaction, role: discord.Role):
    with open("config.json", "w") as file:
        json.dump({"allowed-role": role.id}, file)

    embed = discord.Embed(title="Role Set", description=f"The verified role is now {role.mention}.")
    await interaction.response.send_message(embed=embed)


# Start the bot
bot.run(BOT_TOKEN)
