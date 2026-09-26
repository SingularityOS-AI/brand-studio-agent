import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Extract frames from MP4 and arrange horizontally")
    parser.add_argument("mp4_path", type=Path, help="Path to input MP4 file")
    parser.add_argument("times", type=float, nargs="+", help="Times in seconds to extract")
    parser.add_argument("--out", type=Path, required=True, help="Output PNG path")

    args = parser.parse_args()

    if not args.mp4_path.exists():
        print(f"Error: input file {args.mp4_path} does not exist", file=sys.stderr)
        sys.exit(1)

    filter_complex = ""
    inputs = []

    for i, t in enumerate(args.times):
        filter_complex += f"[{i}:v]select='gte(t,{t})',trim=start_frame=1,setpts=PTS-STARTPTS,scale=360:-1[v{i}];"
        inputs.extend(["-i", str(args.mp4_path)])

    hstack_inputs = "".join(f"[v{i}]" for i in range(len(args.times)))
    filter_complex += f"{hstack_inputs}hstack=inputs={len(args.times)}[outv]"

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-frames:v", "1",
        str(args.out)
    ]

    print(f"Running ffmpeg to generate contact sheet: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"Successfully generated contact sheet at {args.out}")
    except subprocess.CalledProcessError as e:
        print(f"Error running ffmpeg:\n{e.stderr.decode('utf-8')}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
