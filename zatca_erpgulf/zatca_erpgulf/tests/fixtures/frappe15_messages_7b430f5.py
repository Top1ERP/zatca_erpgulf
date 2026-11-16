"""Pinned Frappe15 message functions; source-only offline test reference."""

SOURCE = r'''
def msgprint(
	msg: str,
	title: str | None = None,
	raise_exception: bool | type[Exception] | Exception = False,
	as_table: bool = False,
	as_list: bool = False,
	indicator: Literal["blue", "green", "orange", "red", "yellow"] | None = None,
	alert: bool = False,
	primary_action: str | None = None,
	is_minimizable: bool = False,
	wide: bool = False,
	*,
	realtime=False,
) -> None:
	"""Print a message to the user (via HTTP response).
	Messages are sent in the `__server_messages` property in the
	response JSON and shown in a pop-up / modal.

	:param msg: Message.
	:param title: [optional] Message title. Default: "Message".
	:param raise_exception: [optional] Raise given exception and show message.
	:param as_table: [optional] If `msg` is a list of lists, render as HTML table.
	:param as_list: [optional] If `msg` is a list, render as un-ordered list.
	:param primary_action: [optional] Bind a primary server/client side action.
	:param is_minimizable: [optional] Allow users to minimize the modal
	:param wide: [optional] Show wide modal
	:param realtime: Publish message immediately using websocket.
	"""
	import inspect
	import sys

	msg = safe_decode(msg)
	out = _dict(message=msg)

	def _raise_exception():
		if raise_exception:
			if inspect.isclass(raise_exception) and issubclass(raise_exception, Exception):
				exc = raise_exception(msg)
			elif isinstance(raise_exception, Exception):
				exc = raise_exception
				exc.args = (msg,)
			else:
				exc = ValidationError(msg)
			if out.__frappe_exc_id:
				exc.__frappe_exc_id = out.__frappe_exc_id
			raise exc

	if flags.mute_messages:
		_raise_exception()
		return

	if as_table and type(msg) in (list, tuple):
		out.as_table = 1

	if as_list and type(msg) in (list, tuple):
		out.as_list = 1

	if sys.stdin and sys.stdin.isatty():
		if out.as_list:
			msg = [_strip_html_tags(msg) for msg in out.message]
		else:
			msg = _strip_html_tags(out.message)

	if flags.print_messages and out.message:
		print(f"Message: {_strip_html_tags(out.message)}")

	out.title = title or _("Message", context="Default title of the message dialog")

	if not indicator and raise_exception:
		indicator = "red"

	if indicator:
		out.indicator = indicator

	if is_minimizable:
		out.is_minimizable = is_minimizable

	if alert:
		out.alert = 1

	if raise_exception:
		out.raise_exception = 1
		out.__frappe_exc_id = generate_hash()

	if primary_action:
		out.primary_action = primary_action

	if wide:
		out.wide = wide

	if realtime:
		publish_realtime(event="msgprint", message=out)
	else:
		message_log.append(out)
	_raise_exception()

def throw(
	msg: str,
	exc: type[Exception] | Exception = ValidationError,
	title: str | None = None,
	is_minimizable: bool = False,
	wide: bool = False,
	as_list: bool = False,
	primary_action=None,
) -> None:
	"""Throw execption and show message (`msgprint`).

	:param msg: Message.
	:param exc: Exception class. Default `frappe.ValidationError`
	:param title: [optional] Message title. Default: "Message".
	:param is_minimizable: [optional] Allow users to minimize the modal
	:param wide: [optional] Show wide modal
	:param as_list: [optional] If `msg` is a list, render as un-ordered list.
	:param primary_action: [optional] Bind a primary server/client side action.
	"""
	msgprint(
		msg,
		raise_exception=exc,
		title=title,
		indicator="red",
		is_minimizable=is_minimizable,
		wide=wide,
		as_list=as_list,
		primary_action=primary_action,
	)
'''
