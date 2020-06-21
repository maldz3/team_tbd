# download videos from URLS

import os
import shutil
import requests
from bs4 import BeautifulSoup
from pytube import YouTube

ILLEGAL = ['?', ':', '*', '>', '<', "'", '"', '#', '%', '&', '{', '}', "\\", '/', "$", '!', '@', '+', "`", '|', "=" ]

def clean_title(title):
    title = list(title) #use list to split string on characters
    output = []
    for character in title:
        if character == ' ':
            output.append('-')
        elif character not in ILLEGAL:
            output.append(character)
    return "".join(output)


def download_video(video_url, output_dir):
    if 'youtube.com' in video_url:
        return download_youtube(video_url, output_dir)
    elif 'media.oregonstate.edu' in video_url:
        return download_osu(video_url, output_dir)
    return None


def download_youtube(video_url, output_dir):
    try:
        video = YouTube(video_url)
        title = video.title
        title = clean_title(title)

        streams = video.streams.filter(file_extension="mp4")
        itag = streams[0].itag
        extension = '.' + streams[0].mime_type.split('/')[1]

        # file_directory = os.path.join(output_dir, title)
        video.streams.get_by_itag(itag).download(output_path=output_dir, filename=title)
        return title + extension
    except Exception as e:
        print(f'ERROR in download_youtube: {e}')
        raise


def download_osu(video_url, output_dir):
    try:
        page = requests.get(video_url)
        if (not page.status_code) or (page.status_code >= 400):
            raise Exception('Invalid video URL')

        # use BeautifulSoup to extra video information and video media url
        soup = BeautifulSoup(page.content, 'html.parser')

        title = soup.find('meta', property='og:title')
        url = soup.find('meta', property='og:video')
        vid_type = soup.find('meta', property='og:video:type')
        
        title = clean_title(title['content']) if title else 'untitled'
        url = url['content'] if url else None
        extension = '.' + vid_type['content'].split('/')[1] if vid_type else None
        filename = title + extension
        # print(title, url, vid_type)

        if not url:
            raise Exception('Could not find video URL in given website.')

        # download the video now
        download_path = os.path.join(output_dir, filename)

        r = requests.get(url, allow_redirects=True)
        with open(download_path, 'wb') as output_file:
            output_file.write(r.content)

        return filename

    except Exception as e:
        print(f'ERROR in download_osu: {e}')
        raise
