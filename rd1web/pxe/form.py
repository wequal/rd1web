from django import forms
import re
from django.core.exceptions import ValidationError

class PxeForm(forms.Form):
    mac=forms.CharField(widget=forms.Textarea(attrs={'class':'form-control','style': 'width: 300px;',}),label='MAC')
    image=forms.ChoiceField(choices=[('ubuntu2204-arm64','Ubuntu2204-ARM64'),('ubuntu2204-x86','Ubuntu2204-X86'),('rocky9-arm64','Rocky9-ARM64'),('rocky9-x86','Rocky9-X86')],label='Image')
    location=forms.ChoiceField(choices=[('us_b3','US-B3'),('us_b1','US-B1'),('tw','TW')],label='Location')
    
    test_type = forms.ChoiceField(
        choices=[
            ('', 'Select Test Type'),
            ('burnin', 'BurnIn'),
            ('dc', 'DC'),
            ('ac', 'AC')
        ],
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'test_type'}),
        label='Test Type',
        required=False
    )
    
    burnin_tests = forms.MultipleChoiceField(
        choices=[
            ('SAT', 'SAT'),
            ('IPERF', 'IPERF'),
            ('STRESS', 'STRESS'),
            ('DCGM', 'DCGM'),
            ('FIO', 'FIO'),
            ('NV_GPU', 'NV_GPU'),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        label='BurnIn Tests',
        required=False
    )
    
    sat = forms.FloatField(
        widget=forms.NumberInput(attrs={'class': 'form-control',}),
        label='SAT Duration (hours)',
        required=False
    )
    iperf = forms.FloatField(
        widget=forms.NumberInput(attrs={'class': 'form-control',}),
        label='IPERF Duration (hours)',
        required=False
    )
    stress = forms.FloatField(
        widget=forms.NumberInput(attrs={'class': 'form-control',}),
        label='STRESS Duration (hours)',
        required=False
    )
    fio = forms.FloatField(
        widget=forms.NumberInput(attrs={'class': 'form-control',}),
        label='FIO Duration (hours)',
        required=False
    )
    
    dc_cycle = forms.IntegerField(
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        label='DC Cycle Limit',
        required=False
    )
    dc_interval = forms.IntegerField(
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        label='DC Interval (between cycles) - Optional',
        required=False
    )
    
    pdu_ip = forms.GenericIPAddressField(
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='AC PDU IP',
        required=False
    )
    ports = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='AC Ports Number',
        required=False,
        help_text='Enter port numbers separated by commas'
    )
    ac_cycle = forms.IntegerField(
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        label='AC Cycle Limit',
        required=False
    )
    ac_interval = forms.IntegerField(
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        label='AC Interval (between cycles) - Optional',
        required=False
    )
    
    remove=forms.BooleanField(required=False,label="Remove",initial=False)
    check=forms.BooleanField(required=False,label="Check",initial=False)

    def clean(self):
        cleaned_data = super().clean()
        mac_input = cleaned_data.get("mac", "")
        mac_list = [line.strip() for line in mac_input.splitlines() if line.strip()]
        colon_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
        hyphen_pattern = re.compile(r'^([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}$')
        raw_hex_pattern = re.compile(r'^[0-9A-Fa-f]{12}$')

        invalid_macs = [
            mac for mac in mac_list
            if not (
                colon_pattern.fullmatch(mac)
                or hyphen_pattern.fullmatch(mac)
                or raw_hex_pattern.fullmatch(mac)
            )
        ]

        if invalid_macs:
            self.add_error(
                'mac',
                [f"Invalid MAC address format: {mac}. Use format like 7C:C2:55:7B:8C:AF." for mac in invalid_macs]
            )

        test_type = cleaned_data.get('test_type')
        
        if test_type == 'burnin':
            burnin_tests = cleaned_data.get('burnin_tests', [])
            if 'SAT' in burnin_tests and not cleaned_data.get('sat'):
                self.add_error('sat', 'Duration is required for SAT test')
            if 'IPERF' in burnin_tests and not cleaned_data.get('iperf'):
                self.add_error('iperf', 'Duration is required for IPERF test')
            if 'STRESS' in burnin_tests and not cleaned_data.get('stress'):
                self.add_error('stress', 'Duration is required for STRESS test')
            if 'FIO' in burnin_tests and not cleaned_data.get('fio'):
                self.add_error('fio', 'Duration is required for FIO test')
        
        elif test_type == 'dc':
            if not cleaned_data.get('dc_cycle'):
                self.add_error('dc_cycle', 'Cycle limit is required for DC test')
            # DC interval is now optional - no validation needed
        
        elif test_type == 'ac':
            if not cleaned_data.get('pdu_ip'):
                self.add_error('pdu_ip', 'PDU IP is required for AC test')
            if not cleaned_data.get('ports'):
                self.add_error('ports', 'Ports number is required for AC test')
            if not cleaned_data.get('ac_cycle'):
                self.add_error('ac_cycle', 'Cycle limit is required for AC test')
            # AC interval is now optional - no validation needed

        return cleaned_data
    
    def build_parameters_string(self):
        test_type = self.cleaned_data.get('test_type')
        
        if test_type == 'burnin':
            burnin_tests = self.cleaned_data.get('burnin_tests', [])
            parameters = []
            
            for test in burnin_tests:
                if test == 'SAT':
                    duration = self.cleaned_data.get('sat')
                    parameters.append(f"SAT={duration}")
                elif test == 'IPERF':
                    duration = self.cleaned_data.get('iperf')
                    parameters.append(f"IPERF={duration}")
                elif test == 'STRESS':
                    duration = self.cleaned_data.get('stress')
                    parameters.append(f"STRESS={duration}")
                elif test == 'FIO':
                    duration = self.cleaned_data.get('fio')
                    parameters.append(f"FIO={duration}")
                elif test == 'DCGM':
                    parameters.append("DCGM")
                elif test == 'NV_GPU':
                    parameters.append("NV_GPU")
            
            return f"TEST_TYPE=BURNIN {' '.join(parameters)}"
        
        elif test_type == 'dc':
            cycle = self.cleaned_data.get('dc_cycle')
            interval = self.cleaned_data.get('dc_interval')
            # Build parameter string with optional interval
            parameters = [f"TEST_TYPE=DC", f"CYCLE={cycle}"]
            if interval:  # Only add interval if provided
                parameters.append(f"INTERVAL={interval}")
            return " ".join(parameters)
        
        elif test_type == 'ac':
            pdu_ip = self.cleaned_data.get('pdu_ip')
            ports = self.cleaned_data.get('ports')
            cycle = self.cleaned_data.get('ac_cycle')
            interval = self.cleaned_data.get('ac_interval')
            # Build parameter string with optional interval
            parameters = [f"TEST_TYPE=AC", f"PDU_IP={pdu_ip}", f"PORTS={ports}", f"CYCLE={cycle}"]
            if interval:  # Only add interval if provided
                parameters.append(f"INTERVAL={interval}")
            return " ".join(parameters)
        
        return ""
    

class IpmiForm(forms.Form):
    bmc_ip=forms.CharField(widget=forms.Textarea(attrs={'class':'form-control','style': 'width: 500px;',}),label='BMC IP')
    command=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='Command')
    user=forms.ChoiceField(label='User',widget=forms.Select,choices=[('ADMIN','ADMIN'),('root','root')],required=False)
    pwd=forms.CharField(widget=forms.Textarea(attrs={'class':'form-control','style': 'width: 500px;',}),label='Unique Password',required=False)

class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            if self.required:
                raise forms.ValidationError(self.error_messages["required"])
            else:
                return []

        if isinstance(data, (list, tuple)):
            return [super().clean(d, initial) for d in data]
        else:
            return [super().clean(data, initial)]


class FirmwareUploadForm(forms.Form):
    bmc_ip=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='BMC IP')
    user=forms.ChoiceField(label='User',widget=forms.Select,choices=[('ADMIN','ADMIN'),('root','root')],required=False)
    pwd=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='Unique Password',required=False)
    firmware_file = MultipleFileField(
        widget=MultipleFileInput(attrs={
            'class': 'form-control'
        }),
        label='Firmware Files',
        help_text='Upload multiple firmware files. File names should contain firmware type (BMC/BIOS/CPLD/FPGA)',
        required=False
    )

class UniquePasswordForm(forms.Form):
    bmc_mac = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'style': 'width: 500px;',
            'placeholder': 'Enter BMC MAC addresses (one per line)\nExample:\n7c:c2:55:7b:8c:af\n7c:c2:55:89:01:1f'
        }),
        label='BMC MAC Addresses'
    )

    def clean_bmc_mac(self):
        """Validate MAC addresses format"""
        macs = self.cleaned_data['bmc_mac'].split('\n')
        # Filter out empty lines and strip whitespace
        macs = [mac.strip() for mac in macs if mac.strip()]
        if not macs:
            raise forms.ValidationError("Please enter at least one MAC address")
        return macs

class RmaForm(forms.Form):
    base_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='Base SN')
    rma_number=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='RMA Number')
    mac=forms.CharField(widget=forms.Textarea(attrs={'class':'form-control','style': 'width: 500px;',}),label='MAC')
    image=forms.ChoiceField(choices=[('ubuntu2204-arm64','Ubuntu2204-ARM64'),('ubuntu2204-x86','Ubuntu2204-X86')],label='Image')
    remove=forms.BooleanField(required=False,label="Remove",initial=False)
    check=forms.BooleanField(required=False,label="Check",initial=False)
    tests=forms.ChoiceField(choices=[('generic','Generic'),('coreweave','Coreweave'),],label='Tests')


        
    