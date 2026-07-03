import argparse
import getpass
import logging
import sys

from adl import account, data, device, epub_get, login


def adobe_login(args):
  password = None
  if args.user is not None:
    password = getpass.getpass()

  login.login(args.user, password)


def list_accounts(args):
  print("Accounts (* shows currently used account):")
  for a in data.accounts:
    marker = ' '
    if a.urn == data.config.current_user:
      marker = '*'
    print(("- {} {} - {} ({})".format(marker, a.urn, a.sign_id, a.sign_method)))


def delete_account(args):
  account.account_delete(args.urn)


def set_default_account(args):
  account.set_default_account(args.urn)


def get_ebook(args):
  epub_get.get_ebook(args.filename)


def list_devices(args):
  print("Known devices:")
  a = data.get_current_account()
  if a is not None:
    for d in a.devices:
      print(("-  {} {} - {} ".format(d.name, d.device_id, d.type)))
  else:
    print("No registered device")


def register_device(args):
  device.device_register(args.mountpoint)


def build_parser():
  parser = argparse.ArgumentParser(description='Manipulate ACSM files')
  parser.add_argument('-v', '--verbose', dest="verbose", help="Log verbosely", action="store_true", default=False)
  subparsers = parser.add_subparsers(title="commands", description="available commands", help="additional help")

  parser_get = subparsers.add_parser('get', help='Download ebook from an ACSM file')
  parser_get.add_argument('-f', '--filename', dest="filename", required=True, help='The ACSM file')
  parser_get.set_defaults(func=get_ebook)

  parser_login = subparsers.add_parser('login', help='Login to Content Server')
  parser_login.add_argument('-u', '--user', dest="user", default=None, help='Login with this Adobe ID')
  parser_login.set_defaults(func=adobe_login)

  parser_account = subparsers.add_parser('account', help='Manage accounts')
  account_sp = parser_account.add_subparsers()
  parser_alist = account_sp.add_parser('list', help='list accounts')
  parser_alist.set_defaults(func=list_accounts)
  parser_adel = account_sp.add_parser('delete', help='delete account (be careful !)')
  parser_adel.add_argument('urn', help='The user urn')
  parser_adel.set_defaults(func=delete_account)
  parser_aset = account_sp.add_parser('use', help='Set account to use')
  parser_aset.add_argument('urn', help='The user urn')
  parser_aset.set_defaults(func=set_default_account)

  parser_device = subparsers.add_parser('device', help='Manage devices for current user')
  device_sp = parser_device.add_subparsers()
  parser_dlist = device_sp.add_parser('list', help='list devices')
  parser_dlist.set_defaults(func=list_devices)
  parser_detect = device_sp.add_parser('register', help='Register reader')
  parser_detect.add_argument('mountpoint', help='Reader root fs mountpoint')
  parser_detect.set_defaults(func=register_device)

  return parser


def main(argv=None):
  parser = build_parser()
  args = parser.parse_args(argv)

  if not hasattr(args, 'func'):
    parser.print_help()
    return 1

  if args.verbose:
    loglevel = logging.DEBUG
  else:
    loglevel = logging.INFO
  logging.basicConfig(format='%(levelname)s:%(message)s', level=loglevel)

  args.func(args)
  return 0


if __name__ == "__main__":
  sys.exit(main())
