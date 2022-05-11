"""implementation of bot"""
import asyncio
import logging
from typing import Dict, Callable, List, Optional, Coroutine

from .. import AsyncRunnable, MessageTypes, EventTypes  # interfaces & basics
from .. import Cert, HTTPRequester, WebhookReceiver, WebsocketReceiver, Gateway, Client  # net related
from .. import User, Event, Message  # concepts
from ..command import CommandManager
from ..task import TaskManager

log = logging.getLogger(__name__)

TypeEventHandler = Callable[['Bot', Event], Coroutine]


class Bot(AsyncRunnable):
    """
    Represents a entity that handles msg/events and interact with users/khl server in manners that programmed.
    """
    # components
    client: Client
    command: CommandManager
    task: TaskManager

    # flags
    _is_running: bool

    # internal containers
    _me: Optional[User]
    _event_index: Dict[EventTypes, List[TypeEventHandler]]

    def __init__(self,
                 token: str = '',
                 *,
                 cert: Cert = None,
                 client: Client = None,
                 gate: Gateway = None,
                 out: HTTPRequester = None,
                 compress: bool = True,
                 port=5000,
                 route='/khl-wh'):
        """
        The most common usage: ``Bot(token='xxxxxx')``

        That's enough.

        :param cert: used to build requester and receiver
        :param client: the bot relies on
        :param gate: the client relies on
        :param out: the gate's component
        :param compress: used to tune the receiver
        :param port: used to tune the WebhookReceiver
        :param route: used to tune the WebhookReceiver
        """
        if not token and not cert:
            raise ValueError('require token or cert')
        self._init_client(cert or Cert(token=token), client, gate, out, compress, port, route)
        msg_handler = self._make_msg_handler()
        self.client.register(MessageTypes.TEXT, msg_handler)
        self.client.register(MessageTypes.KMD, msg_handler)
        self.client.register(MessageTypes.SYS, self._make_event_handler())

        self.command = CommandManager()
        self.task = TaskManager()

        self._is_running = False

        self._event_index = {}
        self._tasks = []

    def _init_client(self, cert: Cert, client: Client, gate: Gateway, out: HTTPRequester, compress: bool, port, route):
        """
        construct self.client from args.

        you can init client with kinds of filling ways,
        so there is a priority in the rule: client > gate > out = compress = port = route

        :param cert: used to build requester and receiver
        :param client: the bot relies on
        :param gate: the client relies on
        :param out: the gate's component
        :param compress: used to tune the receiver
        :param port: used to tune the WebhookReceiver
        :param route: used to tune the WebhookReceiver
        :return:
        """
        if client:
            self.client = client
            return
        if gate:
            self.client = Client(gate)
            return

        # client and gate not in args, build them
        _out = out if out else HTTPRequester(cert)
        if cert.type == Cert.Types.WEBSOCKET:
            _in = WebsocketReceiver(cert, compress)
        elif cert.type == Cert.Types.WEBHOOK:
            _in = WebhookReceiver(cert, port=port, route=route, compress=compress)
        else:
            raise ValueError(f'cert type: {cert.type} not supported')

        self.client = Client(Gateway(_out, _in))

    def _make_msg_handler(self) -> Callable:
        """
        construct a function to receive msg from client, and interpret it with _cmd_index
        """

        async def handler(msg: Message):
            await self.command.handle(self.loop, msg, {Message: msg, Bot: self})

        return handler

    def _make_event_handler(self) -> Callable:

        async def handler(event: Event):
            if event.event_type not in self._event_index:
                return
            if not self._event_index[event.event_type]:
                return
            for event_handler in self._event_index[event.event_type]:
                await event_handler(self, event)

        return handler

    def add_event_handler(self, type: EventTypes, handler: TypeEventHandler):
        """add an event handler function for EventTypes `type`"""
        if type not in self._event_index:
            self._event_index[type] = []
        self._event_index[type].append(handler)
        log.debug(f'event_handler {handler.__qualname__} for {type} added')
        return handler

    def on_event(self, type: EventTypes):
        """decorator, register a function to handle events of the type"""

        def dec(func: TypeEventHandler):
            self.add_event_handler(type, func)

        return dec

    async def start(self):
        if self._is_running:
            raise RuntimeError('this bot is already running')
        self.task.schedule()
        await self.client.start()

    def run(self):
        """run the bot in blocking mode"""
        if not self.loop:
            self.loop = asyncio.get_event_loop()
        try:
            self.loop.run_until_complete(self.start())
        except KeyboardInterrupt:
            log.info('see you next time')
