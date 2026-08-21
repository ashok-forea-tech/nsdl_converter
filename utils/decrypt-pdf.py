import sys
import os
import pikepdf


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <file.pdf> <password>")
        sys.exit(1)

    input_file = sys.argv[1]
    password = sys.argv[2]

    base, ext = os.path.splitext(input_file)
    output_file = f"{base}_decrypt{ext}"

    pdf = pikepdf.open(input_file, password=password)
    pdf.save(output_file)


if __name__ == "__main__":
    main()
