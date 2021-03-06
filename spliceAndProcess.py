# This file's functionality is to take a video file path, and spit out slides and audio
# segments from that video file, then to send those
# audio segments to get transcribed, and finally creating a document.
# The document is then returned from the main function spliceAndProcess.
#
# still do to: probably overlap the audio to get better transcription.
#
# example execution of the main function is at the bottom

import os  # for file handling
# this package will have to be installed to the environment to be included.
# to get this package into conda, run from terminal: conda install -c conda-forge moviepy
# pip install moviepy also works if you use pip; added to requirements.txt
from moviepy.video.io.VideoFileClip import VideoFileClip
import numpy as np  # for numerical operations of audio volume

from typing import List
from ibm_watson import SpeechToTextV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
import string
import random
import srt
from fpdf import FPDF, set_global
from googletrans import Translator
import datetime

# setup for ibm watson transcription service
authenticator = IAMAuthenticator(os.environ.get('API_KEY'))
speech_to_text = SpeechToTextV1(
    authenticator=authenticator
)
speech_to_text.set_service_url(os.environ.get('API_URL'))
speech_to_text.set_disable_ssl_verification(True)

# this is just a decimal version of the standard range function
# adapted from https://www.techbeamers.com/python-float-range/#:~:text=Python%20range%20can%20only%20generate,arguments%20are%20of%20integer%20type.
def float_range(start, stop, step):
    while start < stop:
        yield float(start)
        start += step
        start = round(start, 2)


class Segment:
    def __init__(self, start_time, end_time):
        self.startTime = start_time
        self.endTime = end_time
        self.video = None
        self.text = None
        self.audioPath = None
        self.imagePath = None


def createOrCleanOutputFolder(output_dir):
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)
    else:
        fileList = [f for f in os.listdir(
            output_dir)]  # jacked from https://stackoverflow.com/questions/1995373/deleting-all-files-in-a-directory-with-python/1995397
        for f in fileList:
            os.remove(os.path.join(output_dir, f))


# used to find the lowest value in an array near a specified index
def getIndexOfLowestValueInRange(arr, startIndex, searchDistance):
    earliest = max(0, startIndex - searchDistance)
    latest = min(len(arr) - 1, startIndex + searchDistance)
    minVolume = 999999
    minIndex = 0
    for i in range(earliest, latest + 1):
        if arr[i] < minVolume:
            minVolume = arr[i]
            minIndex = i
    return minIndex


def fineTuneTimeCutoffs(clip, times):
    # determine sections of greatest silence, to preferably stop between sentences
    # mainly based on code at:
    # https://zulko.github.io/blog/2014/07/04/automatic-soccer-highlights-compilations-with-python/
    silence_window = 5  # the number of seconds to average when looking for best moments of silence.
    cut = lambda i: clip.audio.subclip(i, i + 1).to_soundarray(fps=10000)
    volume = lambda array: np.sqrt(((1.0 * array) ** 2).mean())
    volumes = [volume(cut(i)) for i in range(0, int(clip.duration - 1))]
    # compute the average volumes over periods of silence_window seconds
    averaged_volumes = np.array([sum(volumes[i:i + silence_window]) / silence_window
                                 for i in range(len(volumes) - silence_window)])

    silence_search_distance = 10
    for i, time in enumerate(times):
        if i != 0:
            times[i] = getIndexOfLowestValueInRange(averaged_volumes, times[i], silence_search_distance) + silence_window // 2  # best if safety check was added here
    print("times after fine tuning: ", times)


def generateSlides(clip: VideoFileClip, segments: List[Segment], output_dir):
    for seg in segments:
        slidePath = os.path.join(output_dir, '{}.png'.format(seg.startTime))
        slideMidPoint = (seg.startTime + seg.endTime) // 2
        clip.save_frame(slidePath, slideMidPoint)
        seg.imagePath = slidePath


def generateAudioClips(clip: VideoFileClip, segments: List[Segment], output_dir):
    # this needs to be done in two loops to avoid assertions from the sub clipping
    for seg in segments:
        seg.video = clip.subclip(seg.startTime, seg.endTime)
    for seg in segments:
        seg.audioPath = output_dir + "/clip_" + str(seg.startTime) + ".mp3"
        seg.video.audio.write_audiofile(seg.audioPath)


def getTimeStamp(segment):
    timestamp = '[' + str(datetime.timedelta(seconds=segment.startTime)) + '-' + str(
        datetime.timedelta(seconds=segment.endTime)).split(".")[0] + "]\n"
    return timestamp

# if a captions file exists, parse that instead of transcription
def sortCaptions(segments: List[Segment], captions_file_path):
    captionsBlob = None
    with open(captions_file_path, "r") as captions_file:
        captionsBlob = captions_file.read()
    captionsGenerator = srt.parse(captionsBlob)

    for caption in captionsGenerator:
        startSecond = int(caption.start.total_seconds())
        text = caption.content
        for seg in segments:
            if seg.startTime <= startSecond < seg.endTime:
                if seg.text is None:
                    timestamp = getTimeStamp(seg)
                    seg.text = timestamp + text
                else:
                    seg.text += " " + text
                break


def generateTranscriptionsFake(segments: List[Segment]):
    for seg in segments:
        paragraph = " ".join(" ".join(
            "".join([random.choice(string.ascii_letters) for i in range(random.randrange(2, 15))]) for _ in
            range(random.randrange(5, 20))) + '.' for i in range(random.randrange(4, 8)))
        timestamp = getTimeStamp(seg)
        seg.text = timestamp
        seg.text += paragraph


def generateTranscriptions(segments: List[Segment]):
    for seg in segments:
        filename = seg.audioPath
        with open(filename, 'rb') as audio_file:
            speech_recognition_results = speech_to_text.recognize(
                audio=audio_file,
                content_type='audio/mp3',
                word_alternatives_threshold=0.9,
				smart_formatting='true'
            ).get_result()

        transcript = []
        for portion in speech_recognition_results['results']:
            # timestamp = portion['word_alternatives'][0]['start_time']
            text = portion['alternatives'][0]['transcript']
            # text_data = dict({'timestamp': timestamp, 'text': text})
            # transcript.append(text_data)
            transcript.append(text)
        timestamp = getTimeStamp(seg)
        seg.text = timestamp
        seg.text += '. '.join(transcript)
        # print("Finished transcription of segment with text:\n", seg.text)


def performTranslation(segments: List[Segment], desired_language):
    # this should automatically detect the source language and convert to desired
    translator = Translator()
    for seg in segments:
        seg.text = translator.translate(seg.text, dest=desired_language).text


set_global("SYSTEM_TTFONTS", os.path.join(os.path.dirname(__file__), 'fonts'))
class PDF(FPDF):
    def __init__(self, header_title):
        FPDF.__init__(self)
        self.headerText = header_title

    def header(self):
        # Arial bold 15
        self.set_font('CyberBit', 'B', 12)
        # Move to the right
        self.cell(50)
        # Title
        self.cell(10, 10, self.headerText)
        # Line break
        self.ln(10)

    # Page footer
    def footer(self):
        # Position at 1.5 cm from bottom
        self.set_y(-15)
        # Arial italic 8
        self.set_font('CyberBit', 'I', 8)
        # Page number
        self.cell(0, 10, 'Page ' + str(self.page_no()) + '/{nb}', 0, 0, 'C')


def generateDocument(video_name, segments: List[Segment], output_dir):
    pdf = PDF(video_name)
    # need outside font to encode foreign characters.
    # see https://stackoverflow.com/questions/56761449/unicodeencodeerror-latin-1-codec-cant-encode-character-u2013-writing-to
    # pdf.set_doc_option('core_fonts_encoding', 'utf-8')
    pdf.core_fonts_encoding = 'utf-8'
    pdf.add_font("CyberBit", style="", fname="Cyberbit.ttf", uni=True)
    pdf.add_font("CyberBit", style="B", fname="Cyberbit.ttf", uni=True)
    pdf.add_font("CyberBit", style="I", fname="Cyberbit.ttf", uni=True)
    pdf.add_font("CyberBit", style="BI", fname="Cyberbit.ttf", uni=True)

    pdf.alias_nb_pages()
    for seg in segments:
        pdf.add_page()
        pdf.set_font('CyberBit', '', 12)
        pdf.image(seg.imagePath, 5, None, 200)
        pdf.ln(5)
        pdf.multi_cell(0, 5, seg.text)

    document_name = video_name + '.pdf'
    path_to_doc = os.path.join(output_dir, document_name)
    pdf.output(path_to_doc, 'F')
    return path_to_doc


# this function does all the stuff listed at the top of this file.
# based on https://stackoverflow.com/questions/43148590/extract-images-using-opencv-and-python-or-moviepy
def spliceAndProcess(video_name, video_folder, time_increment_seconds=60.0, output_dir='slides', desired_language='en'):
    print("video name received", video_name)
    print("video folder received", video_folder)
    # ensure that slide directory exists and is empty
    # this is technically dangerous:
    #   In the finished product we may want to delete dir when we're done, and
    #   bail if dir exists when entering function.
    createOrCleanOutputFolder(output_dir)

    # get video handler and calculate segment times
    fullVideoPath = os.path.join(video_folder, video_name)
    print("full video path", fullVideoPath)

    clip = VideoFileClip(fullVideoPath)

    print("the duration is: ", clip.duration)
    #times = list(float_range(0, clip.duration, time_increment_seconds))
    times = list(range(0, int(clip.duration), int(time_increment_seconds)))
    print("the clips are at: ", times)

    # fine tune the location of time cutoffs to be during moments of silence.
    # does't work that well tho.
    # fineTuneTimeCutoffs(clip, times)

    # add on the end of clip time for last segment info
    times.append(clip.duration)  # add the end time

    # create video segment list to process
    segments = []
    for i in range(0, len(times) - 1):
        segments.append(Segment(times[i], times[i+1]))

    # create image slides
    generateSlides(clip, segments, output_dir)

    # create transcriptions of audio
    possible_captions_file = os.path.splitext(fullVideoPath)[0] + '.' + desired_language + ".srt"
    possible_english_captions_file = os.path.splitext(fullVideoPath)[0] + '.' + 'en' + ".srt"
    # if a captions file exists, parse that instead of transcription
    translatedCaptions = False
    if os.path.isfile(possible_captions_file):
        sortCaptions(segments, possible_captions_file)
        translatedCaptions = True
        print('skip text translation')
    elif os.path.isfile(possible_english_captions_file):
        sortCaptions(segments, possible_english_captions_file)
    else:
        # create audio clips
        generateAudioClips(clip, segments, output_dir)
        generateTranscriptions(segments)

    # translate to another language if desired
    if desired_language != 'en' and not translatedCaptions:
        performTranslation(segments, desired_language)

    # create document
    #pathToDocument = generateDocument(video_name, segments, output_dir)

	# clean up the temp folder of data files no longer needed.
	# code goes here

    # finally, give the document path back to calling function to be delivered to user
    #return pathToDocument
    # line 144 is placeholder only. line 142 should be used when pdf gen is done.
    return segments

def create_imagetext_dictionary(segments: List[Segment]):
    image_text=[]
    for segment in segments:
        image_text.append({
            'image' : segment.imagePath,
            'text' : segment.text
        })
    # print(image_text)
    return image_text

# example function execution
# movieName = 'testVid.mp4'  # name of the video
# movieFolder = ''  # path to folder containing the video
# outputPath = 'slides'  # temp dir to store the files
# timeIncrement = 90.0  # time per slide in seconds
# spliceAndProcess(movieName, movieFolder, timeIncrement, outputPath)
