from pathlib import Path

def cut_cmd(src, dst, start, end, precise=False):
    if precise:
        return ["ffmpeg", "-y", "-ss", start, "-i", src, "-to", end,
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k", dst]
    return ["ffmpeg", "-y", "-ss", start, "-to", end, "-i", src,
            "-c", "copy", dst]

def extract_audio_cmd(src, dst, codec="flac"):
    if codec == "mp3":
        return ["ffmpeg", "-y", "-i", src, "-vn", "-c:a", "libmp3lame", "-q:a", "2", dst]
    if codec == "wav":
        return ["ffmpeg", "-y", "-i", src, "-vn", "-c:a", "pcm_s16le", dst]
    return ["ffmpeg", "-y", "-i", src, "-vn", "-c:a", "flac", dst]

def transform_cmd(src, dst, width="", height="", rotate="none", volume="1.0",
                  fade_in="", fade_out=""):
    vf = []
    af = []
    if width and height:
        vf.append(f"scale={width}:{height}")
    if rotate == "90":
        vf.append("transpose=1")
    elif rotate == "180":
        vf.append("transpose=2,transpose=2")
    elif rotate == "270":
        vf.append("transpose=2")
    if volume and volume != "1.0":
        af.append(f"volume={volume}")
    if fade_in:
        af.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out:
        af.append(f"afade=t=out:st=0:d={fade_out}")
    args = ["ffmpeg", "-y", "-i", src]
    if vf:
        args += ["-vf", ",".join(vf)]
    if af:
        args += ["-af", ",".join(af)]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", dst]
    return args

def replace_audio_cmd(video, audio, dst):
    return ["ffmpeg", "-y", "-i", video, "-i", audio,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-shortest", dst]
