import argparse
import os
import re
from datetime import datetime
from functools import reduce

import requests
from bs4 import BeautifulSoup

DEFAULT_DOWNLOAD_DIR = 'docs'
REQUEST_HEADERS = {
    'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:92.0)'
        ' Gecko/20100101 Firefox/92.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,'
              'image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive'
}
CHUNK_SIZE = 2 ** 16


def clock(f):
    def wrapper(*args, **kwargs):
        start_time = datetime.now()
        f(*args, **kwargs)
        elapsed_time = datetime.now() - start_time
        print(f'Затраченное время: {elapsed_time}')
    return wrapper


@clock
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('username', type=str, help='номер телефона или '
                                                   'электронная почта')
    parser.add_argument('password', type=str)
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='сообщать о ходе загрузки каждого файла')
    parser.add_argument('-d', '--dir', type=str,
                        help='папка, в которую будут загружены файлы',
                        default=DEFAULT_DOWNLOAD_DIR, metavar='<dir>')
    parser.add_argument('-s', '--start', type=int,
                        help='номер файла, начиная с которого '
                             'будет производиться загрузка;'
                             ' нумерация с 1',
                        metavar='<number>')
    parser.add_argument('-e', '--end', type=int,
                        help='номер файла, кончая которым '
                             'будет производиться загрузка;'
                             ' нумерация с 1',
                        metavar='<number>')
    cl_args = parser.parse_args()
    username = cl_args.username
    password = cl_args.password
    cl_args = {
        'verbose': cl_args.verbose,
        'dir': cl_args.dir,
        'start': cl_args.start,
        'end': cl_args.end
    }
    try:
        session, auth_success = login(username, password)
        if not auth_success:
            return
        data = prepare_data(session)
        if not os.path.exists(cl_args.get('dir')):
            os.mkdir(cl_args.get('dir'))
        download_many = download_all
        if cl_args.get('start'):
            download_many = set_start(cl_args.get('start'), download_many)
        if cl_args.get('end'):
            download_many = set_end(cl_args.get('end'), download_many)
        download_many(data, session, cl_args)
        session.close()
    except OSError as e:
        print(f'\n{e}')


def login(username, password):
    session = requests.Session()
    session.headers = REQUEST_HEADERS
    response = session.get('https://m.vk.com/')
    html = BeautifulSoup(response.content, 'html.parser')
    action = html.select('form[method="POST"]')[0]['action']
    data = dict(map(lambda pair: (pair['name'], pair['value']), html.select(
        'form[method="POST"] input[type="hidden"]')))
    data.update({
        'email': username,
        'pass': password
    })
    response = session.post(action, data=data)
    html = BeautifulSoup(response.content, 'html.parser')
    auth_success = False
    if response.url == 'https://m.vk.com/feed':
        auth_success = True
    elif response.url.startswith('https://m.vk.com/login?act=authcheck'):
        print('Требуется двухэтапная верификация')
        auth_success = auth_check(session, response, auth_success)
    elif not html.select('img.captcha_img'):
        print('Данные входа неверны')
    else:
        print('Требуется капча')
    print('Авторизация пройдена'
          if auth_success else 'Авторизация не пройдена')
    return session, auth_success


def auth_check(session, response, auth_success):
    while not auth_success:
        html = BeautifulSoup(response.content, 'html.parser')
        if html.select('.captcha_img'):
            print('Требуется капча')
            break
        action = 'https://m.vk.com/' \
                 + html.select('form[method="post"]')[0]['action']
        data = {'code': input('Verification code: ')}
        response = session.post(action, data=data)
        if response.url == 'https://m.vk.com/feed':
            auth_success = True
    return auth_success


def prepare_data(session):
    print('Подготовка...')
    data = []
    counter = 0
    while True:
        params = {'offset': counter}
        response = session.get('https://m.vk.com/docs', params=params)
        html = BeautifulSoup(response.content, 'html.parser')
        items = html.select('.si_body > a')
        if len(items):
            for item in items:
                name = item.select('.si_owner')[0].text
                data.append({
                    'link': f'https://m.vk.com/{item["href"]}',
                    'name': name,
                    'pos': counter + 1
                })
                counter += 1
        else:
            break
    return data


def download_all(file_args_list, session, cl_args):
    const_args = {
        'session': session,
        'is_finished': {item.get('link'): False for item in file_args_list},
        'percentages': set(range(0, 101)),
        'cl_args': cl_args
    }
    print(f'Количество файлов: {len(file_args_list)}')
    for dictionary in file_args_list:
        dictionary.update(const_args)
        try:
            download_file(**dictionary)
        except OSError as e:
            print(f'\n{e}')
    print('\nВсе файлы загружены')


def format_size(n):
    for unit in ['B', 'KiB', 'MiB', 'GiB']:
        if 1 < n < 1024:
            return f'{round(n, 3)} {unit}'
        n /= 1024


def download_file(link, name, pos, session, is_finished, percentages, cl_args):
    with session.get(link, stream=True) as r:
        verbose = cl_args.get('verbose')
        download_dir = cl_args.get('dir')
        name = correct_file_name(name, download_dir)
        size = int(r.headers.get('content-length'))
        with open(name, mode='wb') as f:
            for i, chunk in enumerate(r.iter_content(CHUNK_SIZE)):
                f.write(chunk)
                if verbose:
                    report_file_progress(pos, name, size, i)
        if not verbose:
            is_finished.update({link: True})
            report_total_progress(percentages, is_finished)


def correct_file_name(name, download_dir):
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    name = os.path.join(download_dir, name)
    name, ext = os.path.splitext(name)
    if not ext or not re.match(r'^.[a-zA-Z]+$', ext):
        ext += '.gif'
    counter = 0
    new_name = f'{name}{ext}'
    while os.path.exists(new_name):
        counter += 1
        new_name = f'{name} ({counter}){ext}'
    return new_name


def report_total_progress(percentages, is_finished):
    share = reduce(lambda a, x: a + int(x), is_finished.values())
    progress = int(round(share / len(is_finished), 2) * 100)
    if progress in percentages:
        percentages.remove(progress)
        print(f'\rГотово: {progress}%', end='')


def report_file_progress(pos, name, size, counter):
    progress = round(CHUNK_SIZE * counter / size * 100)
    if CHUNK_SIZE * (counter + 1) < size:
        print(f'\r{pos}. {name} {format_size(size)} загрузка:'
              f' {progress}%', end='')
    else:
        print(f'\r{pos}. {name} {format_size(size)} загружен')


def set_start(pos, f):
    def wrapper(data, session, cl_args):
        data = data[pos - 1:]
        f(data, session, cl_args)

    return wrapper


def set_end(pos, f):
    def wrapper(data, session, cl_args):
        data = data[:pos]
        f(data, session, cl_args)

    return wrapper


if __name__ == '__main__':
    main()
