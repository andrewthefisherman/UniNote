import os
import re
# import subprocess
import fitz
import google.generativeai as genai

# def run_script(script_name, input_data):
#     script_path = os.path.join(os.getcwd(), script_name)
#     result = subprocess.run(
#         ['python3', script_path, input_data],
#         capture_output=True,
#         text=True
#     )
#     return result.stdout if result.returncode == 0 else result.stderr

# Path to your PDF
pdf_path = "Successioni1_3.pdf"

# Temporary directory to store images
temp_dir = "temp"
if not os.path.exists(temp_dir):
    os.makedirs(temp_dir)

# Open the PDF file
pdf_document = fitz.open(pdf_path)

pdf_images = []
# Iterate through the pages and save as JPGs in the temp folder
for page_num in range(pdf_document.page_count):
    page = pdf_document.load_page(page_num)
    pix = page.get_pixmap()  # Render page to an image
    output_filename = os.path.join(temp_dir, f"{page_num+1}.jpg")
    pix.save(output_filename)  # Save image to temp folder
    pdf_images.append(output_filename)  # Add image file path to list

genai.configure(api_key='AIzaSyAfNPbUKOCWG8u2FgCS3YOsVXxJf2ccpAA')

prompt = 'Analizza l\'immagine e trascrivi esclusivamente il testo contenuto all\'interno di un riquadro contrassegnato da una stella. Se non è presente nessun testo con queste caratteristiche, restituisci solo la parola \"null\". Non trascrivere nessun altro testo presente nell\'immagine, anche se riconosciuto.Converti eventuali notazioni matematiche in LaTeX.'

# Choose a Gemini model.
model = genai.GenerativeModel(model_name="gemini-1.5-pro")

transcriptions = []
image_number = 1
for file in os.listdir(temp_dir):
    sample_file = genai.upload_file(path=f"{temp_dir}/{image_number}.jpg",
                                    display_name=f"Image {image_number}")
    response = model.generate_content([prompt, sample_file])
    output = response.text
    transcriptions += [response.text]
    image_number += 1

print(response.text)
# Clean up: Remove each file inside the temp directory but keep the directory itself
for file_name in os.listdir(temp_dir):
    file_path = os.path.join(temp_dir, file_name)
    if os.path.isfile(file_path):
        os.remove(file_path)  # Delete the file

formatted_transcriptions = []
for transcript in transcriptions:
    result = re.sub(r'\$(.*?)\$', r'eq(\1)', transcript)
    formatted_transcriptions += [result]


#SEI ARRIVATO A SCRIVERE CORRETTAMENTE IL PROMPT E FORMATTARLO SENZA <PGR> MARKER O PROPRIETà. MANCA ANCHE IL TITOLO DELLA NOTA, DATA POSIZIONE O COSE SIMILI. LA FUNZIONE PER RUNNARE UN ALTRO SCRIPT DOVREBBE ANDARE MA IN "NOTION API" TI MANCA PROPRIO AL GESTIONE DEGLI INPUT DA ALTRI SCRIPT. BUON LAVORO!