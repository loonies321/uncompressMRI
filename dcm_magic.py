'''
   Copyright 2022 Maksim Trushin  PET-Technology Podolsk
   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at
       http://www.apache.org/licenses/LICENSE-2.0
   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
'''



import sys
import pydicom
import os


def changeUID(old, new):
        inuque_number = old.value.split('.')[-1]
        tmp = new.value.split('.')
        tmp[-1] = inuque_number
        tmp = '.'.join(tmp)
        new.value = tmp
        tmp = []

def shamanstvo(multifile, normal_files_folder='etalonnoeMRI', ):
    filenames = os.listdir(normal_files_folder) #'MR.GS00471982.Image 1.dcm'
    
    # get the pixel information into a numpy array
    filenameold=multifile                        #'IMG-0001-00001.dcm'
    dsold=pydicom.dcmread(filenameold)
    data = dsold.pixel_array
    per_frame_info = dsold[0x5200, 0x9230]
    #global parameters
    plane_orientation_old = per_frame_info[0][0x0020, 0x9116] #Plane Orientation Sequence
    image_orientation_old = plane_orientation_old[0][0x0020, 0x0037]#(0020, 0037) Image Orientation (Patient)
    instasce_creation_date_old = dsold[0x008, 0x0012]  
    instasce_creation_time_old = dsold[0x008, 0x0013] 
    for i, val in enumerate(data):
        #reading new mri file where we will put data from one slice of multiframe mri
        filename=f'{normal_files_folder}\\{filenames[0]}'#[i]}'
        ds = pydicom.dcmread(filename)
        ds.remove_private_tags()
        #take pixel array from slice 
        pixel_matrix=val#data[0]
        data_downsampling = pixel_matrix[::1, ::1]
        # put pixels from slice of multislice into sigle mri
        ds.PixelData = data_downsampling.tostring()
        # update the information regarding the shape of the data array
        ds.Rows, ds.Columns = data_downsampling.shape
        #elem_shaman.value = elem_old.value
        #save spasing between slices
        slice_info = per_frame_info[i][0x2005, 0x140f] #tags of working slice of multislice mri
        
        #gives unique uid for each frame from multy for every slice
        SOP_instance_UID_frame_old = slice_info[0][0x0008, 0x0018]
        SOP_instance_UID_frame = ds[0x0008, 0x0018]
        changeUID(SOP_instance_UID_frame_old, SOP_instance_UID_frame)
        #
        
        study_instance_UID_old = dsold[0x0020, 0x000d] 
        study_instance_UID = ds[0x0020, 0x000d]
        changeUID(study_instance_UID_old, study_instance_UID)
        
        #
        series_instance_UID_old = dsold[0x0020, 0x000e] 
        series_instance_UID = ds[0x0020, 0x000e] 
        changeUID(series_instance_UID_old, series_instance_UID)
        
        #
        frame_of_reference_UID_old = dsold[0x0020, 0x0052]
        frame_of_reference_UID = ds[0x0020, 0x0052]
        changeUID(frame_of_reference_UID_old, frame_of_reference_UID)
        
        #saving instance creation date and time
        instasce_creation_date = ds[0x008, 0x0012] 
        instasce_creation_date.value = instasce_creation_date_old.value
        instasce_creation_time = ds[0x008, 0x0013] 
        instasce_creation_time.value = instasce_creation_time_old.value
        
        #save slice thiknes
        slice_thiknes = ds[0x0018, 0x0050] #slice thikness of single mri 
        #slice thikness from multiframe of frame in work in cicle
        slice_thiknes_old = slice_info[0][0x0018, 0x0050]
        slice_thiknes.value = slice_thiknes_old.value
        #save slice spacing
        slice_spasing = ds[0x0018, 0x0088]
        slice_spasing_old = slice_info[0][0x0018, 0x0088]
        slice_spasing.value = slice_spasing_old.value
        # (0020, 0013) Instance Number
        instance_number = ds[0x0020, 0x0013]
        instance_number_old = slice_info[0][0x0020, 0x0013]
        instance_number.value = instance_number_old.value
        #(0020, 0032) Image Position (Patient) 
        image_position = ds[0x0020, 0x0032]
        image_position_old = slice_info[0][0x0020, 0x0032]
        image_position.value = image_position_old.value
        # (0020, 0037) Image Orientation (Patient)
        image_orientation = ds[0x0020, 0x0037]
        image_orientation.value = image_orientation_old.value
        #(0028, 0030) Pixel Spacing                       DS: [0.48828125, 0.48828125]
        pixel_spasing = ds[0x0028, 0x0030]
        pixel_spasing_old = slice_info[0][0x0028, 0x0030]
        pixel_spasing.value = pixel_spasing_old.value
        #(0028, 1050) Window Center                       DS: '487.0'
        window_center = ds[0x0028, 0x1050]
        window_center_old = slice_info[0][0x0028, 0x1050]
        window_center.value = window_center_old.value
        #(0028, 1051) Window Width                        DS: '847.0'
        window_width = ds[0x0028, 0x1051]
        window_width_old = slice_info[0][0x0028, 0x1051]
        window_width.value = window_width_old.value
        ds.PatientName = "GRIGOR'EVA S.A"
        ds.save_as(f"after{i}.dcm")
        
        
def write_dicom(pixel_array,filename):

#pixel_array: 2D numpy ndarray.
#filename: string name for the output file.

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = 'Secondary Capture Image Storage'
    file_meta.MediaStorageSOPInstanceUID = '1.3.6.1.4.1.9590.100.1.1.111165684411017669021768385720736873780'
    file_meta.ImplementationClassUID = '1.3.6.1.4.1.9590.100.1.0.100.4.0'
    
    ds = FileDataset(filename, {},file_meta = file_meta,preamble=b'\0'*128)
    ds.Modality = 'OT'
    
    ds.ContentDate = str(datetime.date.today()).replace('-','')
    ds.ContentTime = str(time.time())
    ds.StudyInstanceUID =  '1.3.6.1.4.1.9590.100.1.1.124313977412360175234271287472804872093'
    ds.SeriesInstanceUID = '1.3.6.1.4.1.9590.100.1.1.369231118011061003403421859172643143649'
    ds.SOPInstanceUID =    '1.3.6.1.4.1.9590.100.1.1.111165684411017669021768385720736873780'
    ds.is_little_endian = True
    ds.is_implicit_VR = True
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SecondaryCaptureDeviceManufctur = 'Python 3.7'
    
    ## These are the necessary imaging components of the FileDataset object.
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME1"
    ds.PixelRepresentation = 0
    ds.PlanarConfiguration = 0
    ds.HighBit = 15
    ds.BitsStored = 16
    ds.BitsAllocated = 16
    ds.SmallestImagePixelValue = b'\\x00\\x00'
    ds.LargestImagePixelValue = b'\\xff\\xff'
    ds.Columns = pixel_array[0].shape[1]
    ds.Rows = pixel_array[0].shape[0]
    
    ds.file_meta.TransferSyntaxUID = JPEGExtended
    
    # convert the multiframe image into single frames (Required for compression)
    imagelist = []
    for i in range(len(pixel_array)):
        imagelist.append(Image.fromarray(pixel_array[i]))
    print(len(imagelist))
    
    #create compressed images
    byte_list = []
    for frame in imagelist:
        output = io.BytesIO()
        frame.save(output, format="tiff")
        byte_list.append(output.getvalue())
    
    frame1 = byte_list[0]
    frame2 = byte_list[1]
    frame3 = byte_list[2]
    
    #safe byte-list frames
    ds.PixelData = pydicom.encaps.encapsulate([frame1 , frame2 , frame3])
    
    ds['PixelData'].is_undefined_length = True
    ds.save_as(filename, write_like_original=False) 