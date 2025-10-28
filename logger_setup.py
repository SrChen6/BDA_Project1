import logging
import sys

def setup_loggers():
    log_screen = logging.getLogger('screen_logger')
    log_screen.setLevel(logging.INFO)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    formatter_screen = logging.Formatter('%(asctime)s [%(filename)s:%(lineno)d] - [%(levelname)s] %(message)s')
    sh.setFormatter(formatter_screen)
    log_screen.addHandler(sh)

    log_file = logging.getLogger('file_logger')
    log_file.setLevel(logging.INFO)

    fh = logging.FileHandler('cleaning.log', mode='a', encoding='utf-8')
    fh.setLevel(logging.INFO)
    formatter_file = logging.Formatter('%(asctime)s [%(filename)s:%(lineno)d] - [%(levelname)s] %(message)s')
    fh.setFormatter(formatter_file)
    log_file.addHandler(fh)

    return log_screen, log_file

log_screen, log_file = setup_loggers()
