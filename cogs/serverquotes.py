import pylibmc
import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from .utils import checks
from .utils.chat_formatting import escape_mass_mentions, pagify
import os
from random import choice as randchoice
import json
import requests
import ast


try:
    from tabulate import tabulate
except Exception as e:
    raise RuntimeError("You must run `pip3 install tabulate`.") from e

PATH = 'data/serverquotes/'
JSON = PATH + 'quotes.json'

print('Path to serverquotes quote list: ' + PATH)


__version__ = '1.5.2'

if os.environ.get('IS_HEROKU') == 'True':
    servers = os.environ.get('MEMCACHIER_SERVERS', '').split(',')
    user = os.environ.get('MEMCACHIER_USERNAME', '')
    password = os.environ.get('MEMCACHIER_PASSWORD', '')
    print('MemCache settings loaded')

    mc = pylibmc.Client(servers, binary=True,
                        username=user, password=password,
                        behaviors={
                          # Faster IO
                          "tcp_nodelay": True,

                          # Keep connection alive
                          'tcp_keepalive': True,

                          # Timeout for set/get requests
                          'connect_timeout': 2000, # ms
                          'send_timeout': 750 * 1000, # us
                          'receive_timeout': 750 * 1000, # us
                          '_poll_timeout': 2000, # ms

                          # Better failover
                          'ketama': True,
                          'remove_failed': 1,
                          'retry_timeout': 2,
                          'dead_timeout': 30,
                        })


class ServerQuotes:

    def __init__(self, bot):
        self.bot = bot
        if os.environ.get('IS_HEROKU') == 'True':
            myjson_url = mc.get('json_url')
            print('myjson_url = ' + str(myjson_url))
            if myjson_url is None:
                myjson_url = os.environ.get('JSON_URL')
            print('myjson_url = ' + myjson_url)
            resp = requests.get(myjson_url)
            data = json.loads(resp.text)
            self.quotes = data
            print('Quotes loaded from Myjson')
        else:
            self.quotes = dataIO.load_json(JSON)
            print('Quotes loaded from ' + JSON)

    def _get_random_quote(self, ctx):
        sid = ctx.message.server.id
        if sid not in self.quotes or len(self.quotes[sid]) == 0:
            raise AssertionError("There are no quotes in this server!")
        quotes = list(enumerate(self.quotes[sid]))
        return randchoice(quotes)

    def _get_random_author_quote(self, ctx, author):
        sid = ctx.message.server.id

        if sid not in self.quotes or len(self.quotes[sid]) == 0:
            raise AssertionError("There are no quotes in this server!")

        if isinstance(author, discord.User):
            uid = author.id
            quotes = [(i, q) for i, q in enumerate(self.quotes[sid]) if q['author_id'] == uid]
        else:
            quotes = [(i, q) for i, q in enumerate(self.quotes[sid]) if q['author_name'] == author]

        if len(quotes) == 0:
            raise commands.BadArgument("There are no quotes by %s." % author)
        return randchoice(quotes)

    def _add_quote(self, ctx, author, message):
        sid = ctx.message.server.id
        aid = ctx.message.author.id
        if sid not in self.quotes:
            self.quotes[sid] = []

        author_name = 'Unknown'
        author_id = None

        if isinstance(author, discord.User):
            author_name = author.display_name
            author_id = author.id
        elif isinstance(author, str):
            author_name = author

        quote = {'added_by': aid,
                 'author_name': author_name,
                 'author_id': author_id,
                 'text': escape_mass_mentions(message)}

        self.quotes[sid].append(quote)
        dataIO.save_json(JSON, self.quotes)
        if os.environ.get('IS_HEROKU') == 'True':
            self._upload_quotes()

    if os.environ.get('IS_HEROKU') == 'True':
        def _upload_quotes(self):
            r = requests.post('https://api.myjson.com/bins', json=self.quotes)
            print(r)
            print('Quotes saved to Myjson')
            print('New Myjson URL: ' + ast.literal_eval(r.text)['uri'])
            mc.set('json_url', ast.literal_eval(r.text)['uri'])
            print('New Myjson URL saved to MemCache')

    def _quote_author(self, ctx, quote):
        if quote['author_id']:
            name = self._get_name_by_id(ctx, quote['author_id'])
            if quote['author_name'] and not name:
                name = quote['author_name']
                name += " (non-present user ID#%s)" % (quote['author_id'])
            return name
        elif quote['author_name']:
            return quote['author_name']
        else:
            return "Unknown"

    def _format_quote(self, ctx, quote):
        qid, quote = quote
        author = self._quote_author(ctx, quote)
        return '"%s"\n—%s (quote #%i)' % (quote['text'], author, qid + 1)

    def _get_name_by_id(self, ctx, uid):
        member = discord.utils.get(ctx.message.server.members, id=uid)
        if member:
            return member.display_name
        else:
            return None

    def _get_quote(self, ctx, author_or_num=None):
        sid = ctx.message.server.id
        if type(author_or_num) is discord.Member:
            return self._get_random_author_quote(ctx, author_or_num)
        if author_or_num:
            try:
                quote_id = int(author_or_num)
                if quote_id > 0 and quote_id <= len(self.quotes[sid]):
                    return (quote_id - 1, self.quotes[sid][quote_id - 1])
                else:
                    raise commands.BadArgument("Quote #%i does not exist." % quote_id)
            except ValueError:
                pass

            try:
                author = commands.MemberConverter(ctx, author_or_num).convert()
            except commands.errors.BadArgument:
                author = author_or_num.strip(' \t\n\r\x0b\x0c-–—')  # whitespace + dashes
            return self._get_random_author_quote(ctx, author)

        return self._get_random_quote(ctx)

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def rmquote(self, ctx, num: int):
        """Deletes a quote by its number

           Use [p]lsquotes to find quote numbers
           Example: !delquote 3"""
        sid = ctx.message.server.id
        if num > 0 and num <= len(self.quotes[sid]):
            del self.quotes[sid][num - 1]
            await self.bot.say("Quote #%i deleted." % num)
            dataIO.save_json(JSON, self.quotes)
            if os.environ.get('IS_HEROKU') == 'True':
                self._upload_quotes()
        else:
            await self.bot.say("Quote #%i does not exist." % num)

    @commands.command(pass_context=True, no_pm=True)
    async def lsquotes(self, ctx):
        """Displays a list of all quotes"""
        sid = ctx.message.server.id
        quotes = self.quotes.get(sid, [])
        if not quotes:
            await self.bot.say("There are no quotes in this server!")
            return
        else:
            msg = await self.bot.say("Sending you the list via DM.")

        header = ['#', 'Author', 'Added by', 'Quote']
        table = []
        for i, q in enumerate(quotes):
            text = q['text']
            if len(text) > 60:
                text = text[:60 - 3] + '...'
            name = self._get_name_by_id(ctx, q['added_by'])
            if not name:
                name = "(non-present user ID#%s)" % q['added_by']
            table.append((i + 1, self._quote_author(ctx, q), name, text))
        tabulated = tabulate(table, header)
        try:
            for page in pagify(tabulated, ['\n']):
                await self.bot.whisper('```\n%s\n```' % page)
        except discord.errors.HTTPException:
            err = "I can't send the list unless you allow DMs from server members."
            await self.bot.edit_message(msg, new_content=err)

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def addquote(self, ctx, message: str, *, author: str = None):
        """Adds a quote to the server quote list. The quote must be enclosed
        in \"double quotes\". If a member mention or name is the last argument,
        the quote will be stored as theirs. If not, the last argument will
        be stored as the quote's author. If left empty, "Unknown" is used.
        """
        if author:
            try:
                author = commands.MemberConverter(ctx, author).convert()
            except commands.errors.BadArgument:
                author = author.strip(' \t\n\r\x0b\x0c-–—')  # whitespace + dashes

        self._add_quote(ctx, author, message)
        await self.bot.say("Quote added.")

    @commands.command(pass_context=True, no_pm=True)
    @commands.cooldown(10, 5, commands.BucketType.channel)
    async def quote(self, ctx, *, author_or_num: str = None):
        """Say a stored quote!

        Without any arguments, this command randomly selects from all stored
        quotes. If you supply an author name, it randomly selects from among
        that author's quotes. Finally, if given a number, that specific quote
        will be said, assuming it exists. Use [p]lsquotes to show all quotes.
        """

        sid = ctx.message.server.id
        if sid not in self.quotes or len(self.quotes[sid]) == 0:
            await self.bot.say("There are no quotes in this server!")
            return

        try:
            quote = self._get_quote(ctx, author_or_num)
        except commands.BadArgument:
            if author_or_num.lower().strip() in ['me', 'myself', 'self']:
                quote = self._get_quote(ctx, ctx.message.author)
            else:
                raise
        await self.bot.say(self._format_quote(ctx, quote))


def check_folder():
    if not os.path.exists(PATH):
        print("Creating serverquotes folder...")
        os.makedirs(PATH)


def check_file():
    if not dataIO.is_valid_json(JSON):
        print("Creating empty quotes.json...")
        dataIO.save_json(JSON, {})


def setup(bot):
    check_folder()
    check_file()
    n = ServerQuotes(bot)
    bot.add_cog(n)
    
