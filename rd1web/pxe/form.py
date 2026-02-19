from django import forms
import re
from django.core.exceptions import ValidationError
from .models import RmaTestingDb, RmaGbDb, RmaPcieDb

BLANK_BMC_CHOICE = [('', '-- Select BMC IP --')]
###
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

    def __init__(self, *args, **kwargs):
        rma = kwargs.pop('rma', False)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if rma:
            # In RMA mode, BMC IP is a manual text input
            self.fields['bmc_ip'] = forms.CharField(
                widget=forms.TextInput(attrs={
                    'class': 'form-control', 
                    'style': 'width: 500px;',
                    'placeholder': 'Enter BMC IP address'
                }),
                label='BMC IP'
            )
            
            # In RMA mode, Password is a single text input, prefilled
            self.fields['pwd'] = forms.CharField(
                initial='Golden@1234',
                widget=forms.TextInput(attrs={'class': 'form-control', 'style': 'width: 500px;'}),
                label='Unique Password',
                required=False
            )
        else:
            # Standard mode - ensure widget attributes match template needs (if using {{ form.field }})
            self.fields['bmc_ip'].widget.attrs.update({
                'rows': '4',
                'placeholder': 'Enter BMC IP addresses (one per line)\nExample:\n192.168.1.100\n192.168.1.101'
            })
            self.fields['pwd'].widget.attrs.update({
                'rows': '4',
                'placeholder': 'Enter passwords (one per line)\nMust match order of IP addresses'
            })

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

    def __init__(self, *args, **kwargs):
        rma = kwargs.pop('rma', False)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if rma:
            # In RMA mode, BMC IP is a manual text input
            self.fields['bmc_ip'] = forms.CharField(
                widget=forms.TextInput(attrs={
                    'class': 'form-control', 
                    'style': 'width: 500px;',
                    'placeholder': 'Enter BMC IP address'
                }),
                label='BMC IP'
            )
            
            # In RMA mode, Password is a single text input, prefilled
            self.fields['pwd'].initial = 'Golden@1234'
        # Standard mode default widget is already TextInput for FirmwareUploadForm, so no else block needed for pwd widget type change

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
    base_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='Base SN',required=True)
    replacement_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='GPUBOARD/UBB8 replacement SN',required=False)
    notice=forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='Notice',required=False)
    rma_number=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='RMA Number',required=False)
    dcgmr4_loop = forms.IntegerField(
        required=False,
        min_value=1,
        label='DCGM R4 Loop',
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'autocomplete': 'off',
            'min': '1',
            'step': '1',
        }),
    )
    bmc_ip=forms.ChoiceField(choices=[], widget=forms.Select(attrs={'class':'form-control','style': 'width: 500px;',}),label='BMC IP')
    image=forms.ChoiceField(choices=[('','-- Select Image --'),('ubuntu2204-x86-rma','H100/200'),('ubuntu2204-b200-rma','B200'),('ubuntu2204-gb200','GB200'),('ubuntu2204-gb200','GH200'),('ubuntu2204-mi300x','MI300X'),('ubuntu2204-mi325x','MI325X'),('ubuntu2204-mi355x','MI355X')],label='Image')
    remove=forms.BooleanField(required=False,label="Remove",initial=False)
    check=forms.BooleanField(required=False,label="Check",initial=False)
    fw_update=forms.BooleanField(required=False,label="Firmware Update",initial=False)
    eco_number=forms.CharField(required=False,label='ECO Number',widget=forms.Select(attrs={'class':'form-control eco-select','style': 'width: 500px;'}))
    gpu_model=forms.ChoiceField(choices=[('','-- Select GPU Model --'),('h100','H100'),('h200','H200')],required=False,label='GPU Model',widget=forms.Select(attrs={'class':'form-control','style': 'width: 500px;'}))
    cooling=forms.ChoiceField(choices=[('','-- Select Cooling --'),('AC','AC'),('LC','LC')],required=False,label='Cooling',widget=forms.Select(attrs={'class':'form-control','style': 'width: 500px;'}))
    tests = forms.MultipleChoiceField(
        choices=[
            ('default', 'Default'),
            ('pre_gpu_test', 'Pre GPU Test'),
            ('dcgm', 'DCGM'),
            ('dcgm_r4', 'DCGM R4'),
            ('fd2', 'FD2'),
            ('gpudiag', 'GPU Field Diag'),
            ('level3_test', 'AGHFC Level 3'),
            ('remote_fw_update', 'Remote FW Update'),
            ('all_log', 'All Log'),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        label='Tests',
        required=False
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Populate BMC IP choices based on user's linked golden numbers (blank default)
        if user:
            from .models import RmaTestingDb
            linked_entries = RmaTestingDb.objects.filter(linked_user=user).order_by('bmc_ip')
            self.fields['bmc_ip'].choices = BLANK_BMC_CHOICE + [(entry.bmc_ip, f"{entry.bmc_ip} - {entry.golden_number}") for entry in linked_entries]
        else:
            self.fields['bmc_ip'].choices = BLANK_BMC_CHOICE

    def clean_tests(self):
        """Validate that Default and All Log are not combined with other tests or firmware update."""
        tests = self.cleaned_data.get('tests', [])

        # Default test cannot be combined with any specific tests, All Log, or Remote FW Update
        if 'default' in tests:
            specific_tests = [test for test in tests if test not in ('default',)]
            if specific_tests:
                raise ValidationError(
                    "Default test cannot be combined with specific tests (Pre GPU Test, DCGM, FD2, GPU Field Diag, AGHFC Level 3, All Log, Remote FW Update). "
                    "Please select either Default OR any combination of the specific tests (excluding All Log and Remote FW Update)."
                )

        # All Log must be selected alone (no other tests)
        if 'all_log' in tests and len(tests) > 1:
            raise ValidationError(
                "All Log cannot be combined with other tests, Firmware Update, or Remote FW Update. Please select only the All Log option."
            )

        # Remote FW Update must be selected alone (no other tests)
        if 'remote_fw_update' in tests and len(tests) > 1:
            raise ValidationError(
                "Remote FW Update cannot be combined with other tests or Firmware Update. Please select only the Remote FW Update option."
            )

        return tests
    
    def clean_replacement_sn(self):
        """Validate that replacement_sn does not start with S9 or s9"""
        replacement_sn = self.cleaned_data.get('replacement_sn', '').strip()
        
        # Only validate if a value is provided (field is optional)
        if replacement_sn:
            if replacement_sn.upper().startswith('S9'):
                raise ValidationError(
                    "GPUBOARD/UBB8 replacement SN cannot start with S9 or s9"
                )
        
        return replacement_sn

    def clean_notice(self):
        """Keep Notice safe for shell + tests_param tokenization."""
        notice = self.cleaned_data.get('notice', '').strip()
        if notice:
            if any(ch in notice for ch in ("'", '"')):
                raise ValidationError("Notice cannot contain quotes.")
            if "\n" in notice or "\r" in notice:
                raise ValidationError("Notice must be a single line.")
        return notice


class PcieGpuForm(forms.Form):
    rma_number=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','style': 'width: 500px;',}),label='RMA Number',required=False)
    
    # GPU1-8 SN
    gpu1_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='GPU1(BMC GPU12) SN',required=False)
    gpu2_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='GPU2(BMC GPU11) SN',required=False)
    gpu3_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='GPU3(BMC GPU10) SN',required=False)
    gpu4_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='GPU4(BMC GPU9) SN',required=False)
    gpu5_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='GPU5(BMC GPU4) SN',required=False)
    gpu6_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='GPU6(BMC GPU3) SN',required=False)
    gpu7_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='GPU7(BMC GPU2) SN',required=False)
    gpu8_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='GPU8(BMC GPU1) SN',required=False)

    # Replacement GPU1-8 SN
    rg1_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='Replacement GPU1(BMC GPU12) SN',required=False)
    rg2_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='Replacement GPU2(BMC GPU11) SN',required=False)
    rg3_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='Replacement GPU3(BMC GPU10) SN',required=False)
    rg4_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='Replacement GPU4(BMC GPU9) SN',required=False)
    rg5_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='Replacement GPU5(BMC GPU4) SN',required=False)
    rg6_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='Replacement GPU6(BMC GPU3) SN',required=False)
    rg7_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='Replacement GPU7(BMC GPU2) SN',required=False)
    rg8_sn=forms.CharField(widget=forms.TextInput(attrs={'class':'form-control'}),label='Replacement GPU8(BMC GPU1) SN',required=False)

    show_replacement=forms.BooleanField(required=False,label="Replacement GPU SN",initial=False)
    bmc_ip=forms.ChoiceField(choices=[], widget=forms.Select(attrs={'class':'form-control','style': 'width: 500px;',}),label='BMC IP')
    image=forms.ChoiceField(choices=[('','-- Select Image --'),('ubuntu2204-x86-rma','Ubuntu2204')],label='Image')
    
    fw_update=forms.BooleanField(required=False,label="Firmware Update",initial=False)
    dcgmr4_loop = forms.IntegerField(
        required=False,
        min_value=1,
        label='DCGM R4 Loop',
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'autocomplete': 'off',
            'min': '1',
            'step': '1',
        }),
    )
    
    tests = forms.MultipleChoiceField(
        choices=[
            ('default', 'Default'),
            ('pre_gpu_test', 'Pre GPU Test'),
            ('fd2', 'FD'),
            ('dcgm_r4', 'DCGM R4'),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        label='Tests',
        required=False
    )
    
    remove=forms.BooleanField(required=False,label="Remove",initial=False)
    check=forms.BooleanField(required=False,label="Check",initial=False)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Populate BMC IP choices based on user's linked golden numbers from PCIE DB (blank default)
        if user:
            from .models import RmaPcieDb
            linked_entries = RmaPcieDb.objects.filter(linked_user=user).order_by('bmc_ip')
            self.fields['bmc_ip'].choices = BLANK_BMC_CHOICE + [(entry.bmc_ip, f"{entry.bmc_ip} - {entry.golden_number}") for entry in linked_entries]
        else:
            self.fields['bmc_ip'].choices = BLANK_BMC_CHOICE

    def clean_tests(self):
        """Validate that Default is not combined with other tests."""
        tests = self.cleaned_data.get('tests', [])
        if 'default' in tests and len(tests) > 1:
            raise ValidationError(
                "Default test cannot be combined with other tests. "
                "Please select either Default OR any combination of the specific tests."
            )
        return tests


class GbGpuForm(forms.Form):
    """
    Form for GB GPU Test (GB200/GB300) - restricted image + tests.
    Uses the same BMC IP choice population as other RMA forms.
    """
    base_sn_1 = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'style': 'width: 500px;'}),
        label='Base SN 1',
        required=True,
    )
    base_sn_2 = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'style': 'width: 500px;'}),
        label='Base SN 2',
        required=True,
    )
    system_sn = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'style': 'width: 500px;'}),
        label='System SN',
        required=True,
    )
    notice = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'style': 'width: 500px;'}),
        label='Notice',
        required=False,
    )
    rma_number = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'style': 'width: 500px;'}),
        label='RMA Number',
        required=False,
    )
    dcgmr4_loop = forms.IntegerField(
        required=False,
        min_value=1,
        label='DCGM R4 Loop',
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'autocomplete': 'off',
            'min': '1',
            'step': '1',
        }),
    )
    bmc_ip = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={'class': 'form-control', 'style': 'width: 500px;'}),
        label='BMC IP',
    )
    image = forms.ChoiceField(
        choices=[
            ('', '-- Select Image --'),
            ('ubuntu2204-gb200', 'GB200'),
            ('ubuntu2204-gb300', 'GB300'),
        ],
        label='Image',
    )
    tests = forms.MultipleChoiceField(
        choices=[
            ('default', 'Default'),
            ('pre_gpu_test', 'Pre GPU Test'),
            ('dcgm_r4', 'DCGM R4'),
            ('fd2', 'FD2'),
            ('hmc_log', 'HMC Log'),
            ('nvlink', 'NVLINK'),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        label='Tests',
        required=False,
    )
    remove = forms.BooleanField(required=False, label="Remove", initial=False)
    check = forms.BooleanField(required=False, label="Check", initial=False)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Populate BMC IP choices based on user's linked golden numbers (blank default, same as RMA/PCIE)
        if user:
            linked_entries = RmaGbDb.objects.filter(linked_user=user).order_by('bmc_ip')
            self.fields['bmc_ip'].choices = BLANK_BMC_CHOICE + [(entry.bmc_ip, f"{entry.bmc_ip} - {entry.golden_number}") for entry in linked_entries]
        else:
            self.fields['bmc_ip'].choices = BLANK_BMC_CHOICE

    def clean_tests(self):
        """Validate that Default and HMC Log are exclusive selections."""
        tests = self.cleaned_data.get('tests', [])

        if 'default' in tests and len(tests) > 1:
            raise ValidationError(
                "Default test cannot be combined with other tests. "
                "Please select either Default OR any combination of the specific tests."
            )

        if 'hmc_log' in tests and len(tests) > 1:
            raise ValidationError(
                "HMC Log cannot be combined with other tests. Please select only the HMC Log option."
            )

        return tests

    def _clean_sn_token(self, field_name: str, label: str) -> str:
        """
        Ensure SN fields are safe for space-delimited tests_param tokens.
        Disallow quotes/newlines/whitespace.
        """
        value = (self.cleaned_data.get(field_name) or "").strip()
        if not value:
            # required=True should catch this, but keep it explicit
            raise ValidationError(f"{label} is required.")
        if any(ch in value for ch in ("'", '"')):
            raise ValidationError(f"{label} cannot contain quotes.")
        if "\n" in value or "\r" in value:
            raise ValidationError(f"{label} must be a single line.")
        if any(ch.isspace() for ch in value):
            raise ValidationError(f"{label} cannot contain whitespace.")
        return value

    def clean_base_sn_1(self):
        return self._clean_sn_token("base_sn_1", "Base SN 1")

    def clean_base_sn_2(self):
        return self._clean_sn_token("base_sn_2", "Base SN 2")

    def clean_system_sn(self):
        return self._clean_sn_token("system_sn", "System SN")

    def clean_notice(self):
        """Keep Notice safe for shell + tests_param tokenization."""
        notice = self.cleaned_data.get('notice', '').strip()
        if notice:
            if any(ch in notice for ch in ("'", '"')):
                raise ValidationError("Notice cannot contain quotes.")
            if "\n" in notice or "\r" in notice:
                raise ValidationError("Notice must be a single line.")
        return notice


class RmaGeneralForm(forms.Form):
    """Form for RMA General TEST - simplified version without golden number dependencies"""
    system_sn = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'style': 'width: 500px;',
        }),
        label='System SN',
        required=False
    )
    rma_number = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'style': 'width: 500px;',
        }),
        label='RMA Number',
        required=False
    )
    nic_mac = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'style': 'width: 500px;',
            'placeholder': 'e.g., ac:1f:6b:35:6f:19 or ac-1f-6b-35-6f-19 or ac1f6b356f19'
        }),
        label='NIC MAC',
        required=False,
        help_text='Enter MAC address in any format (with colons, dashes, or without separators)'
    )
    image = forms.ChoiceField(
        choices=[
            ('','-- Select Image --'),
            ('ubuntu2204-x86-rma', 'H100/200'),
            ('ubuntu2204-gb200', 'GB200'),
            ('ubuntu2204-b200-rma', 'B200'),
            ('ubuntu2204-mi300x', 'MI300X'),
            ('ubuntu2204-mi325x', 'MI325X'),
            ('ubuntu2204-mi355x', 'MI355X')
        ],
        label='Image'
    )
    remove = forms.BooleanField(required=False, label="Remove", initial=False)
    check = forms.BooleanField(required=False, label="Check", initial=False)
    
    def clean_nic_mac(self):
        """Normalize MAC address to lowercase without separators"""
        mac_input = self.cleaned_data.get('nic_mac', '')
        if not mac_input:
            return ''
        
        # Remove common separators and convert to lowercase
        normalized = mac_input.strip().replace(':', '').replace('-', '').lower()
        
        # Validate format (12 hex characters)
        if len(normalized) != 12:
            raise ValidationError(
                f"Invalid MAC address length. Expected 12 characters, got {len(normalized)}. "
                f"Example: ac1f6b356f19 or ac:1f:6b:35:6f:19"
            )
        
        if not all(c in '0123456789abcdef' for c in normalized):
            raise ValidationError(
                "Invalid MAC address format. Must contain only hexadecimal characters (0-9, a-f). "
                "Example: ac1f6b356f19 or ac:1f:6b:35:6f:19"
            )
        
        return normalized


class RmaTestingDbForm(forms.ModelForm):
    """Form for adding/editing RMA Testing DB entries"""
    
    class Meta:
        model = RmaTestingDb
        fields = ['bmc_mac', 'bmc_ip', 'bmc_password', 'lan0_mac', 'lan1_mac', 'golden_number']
        widgets = {
            'bmc_mac': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'xx:xx:xx:xx:xx:xx',
                'pattern': '[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}'
            }),
            'bmc_ip': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '192.168.1.100'
            }),
            'bmc_password': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter BMC password'
            }),
            'lan0_mac': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'xx:xx:xx:xx:xx:xx',
                'pattern': '[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}'
            }),
            'lan1_mac': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'xx:xx:xx:xx:xx:xx',
                'pattern': '[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}'
            }),
            'golden_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Golden Number'
            }),
        }


class RmaGbDbForm(forms.ModelForm):
    """Form for adding/editing RMA GB DB entries (LAN0 only)"""

    class Meta:
        model = RmaGbDb
        fields = ['bmc_mac', 'bmc_ip', 'bmc_password', 'lan0_mac', 'golden_number']
        widgets = {
            'bmc_mac': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'xx:xx:xx:xx:xx:xx',
                'pattern': '[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}'
            }),
            'bmc_ip': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '192.168.1.100'
            }),
            'bmc_password': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter BMC password'
            }),
            'lan0_mac': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'xx:xx:xx:xx:xx:xx',
                'pattern': '[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}'
            }),
            'golden_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Golden Number'
            }),
        }


class RmaGbDbSearchForm(forms.Form):
    """Form for searching RMA GB DB entries"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by MAC address, IP, or password...',
            'id': 'search-input'
        }),
        label='Search'
    )

    def clean_search(self):
        """Clean and validate search input"""
        search = self.cleaned_data.get('search', '').strip()
        return search


class RmaTestingDbSearchForm(forms.Form):
    """Form for searching RMA Testing DB entries"""
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by MAC address, IP, or password...',
            'id': 'search-input'
        }),
        label='Search'
    )
    
    def clean_search(self):
        """Clean and validate search input"""
        search = self.cleaned_data.get('search', '').strip()
        return search


class RmaPcieDbForm(forms.ModelForm):
    """Form for adding/editing RMA PCIE DB entries (LAN1 optional)"""

    class Meta:
        model = RmaPcieDb
        fields = ['bmc_mac', 'bmc_ip', 'bmc_password', 'lan0_mac', 'lan1_mac', 'golden_number']
        widgets = {
            'bmc_mac': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'xx:xx:xx:xx:xx:xx',
                'pattern': '[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}'
            }),
            'bmc_ip': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '192.168.1.100'
            }),
            'bmc_password': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter BMC password'
            }),
            'lan0_mac': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'xx:xx:xx:xx:xx:xx',
                'pattern': '[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}'
            }),
            'lan1_mac': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'xx:xx:xx:xx:xx:xx (optional)',
                'pattern': '[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}[:-]?[0-9A-Fa-f]{2}'
            }),
            'golden_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Golden Number'
            }),
        }


class RmaPcieDbSearchForm(forms.Form):
    """Form for searching RMA PCIE DB entries"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by MAC address, IP, or password...',
            'id': 'search-input'
        }),
        label='Search'
    )

    def clean_search(self):
        """Clean and validate search input"""
        search = self.cleaned_data.get('search', '').strip()
        return search


class EcoFolderForm(forms.Form):
    """Form for creating new ECO folder"""
    eco_number = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter ECO number (e.g., 31882)',
        }),
        label='ECO Number',
        help_text='Enter the ECO number for the new folder'
    )
    
    def clean_eco_number(self):
        """Clean and validate ECO number"""
        eco_number = self.cleaned_data.get('eco_number', '').strip()
        if not eco_number:
            raise forms.ValidationError('ECO number cannot be empty')
        # Remove any potentially dangerous characters for filesystem
        import re
        if re.search(r'[/\\<>:"|?*]', eco_number):
            raise forms.ValidationError('ECO number contains invalid characters')
        return eco_number


class ModelFolderForm(forms.Form):
    """Form for creating new Model folder under pcie"""
    model_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '',
        }),
        label='Model Name',
        help_text='Enter the model name for the new folder'
    )
    
    def clean_model_name(self):
        """Clean and validate model name"""
        model_name = self.cleaned_data.get('model_name', '').strip()
        if not model_name:
            raise forms.ValidationError('Model name cannot be empty')
        # Remove any potentially dangerous characters for filesystem
        import re
        if re.search(r'[/\\<>:"|?*]', model_name):
            raise forms.ValidationError('Model name contains invalid characters')
        return model_name


class FirmwareInventoryUploadForm(forms.Form):
    """Form for uploading firmware files to ECO folder"""
    
    # GPU field (required for all products)
    gpu_file = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.bin,.rom,.fw,.img',
        }),
        label='GPU Firmware',
        help_text='Upload GPU firmware file'
    )
    
    # Retimer 5 (only for H100/H200 products)
    retimer_5_file = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.bin,.rom,.fw,.img',
        }),
        label='Retimer 5 Firmware',
        help_text='Upload Retimer 5 firmware file'
    )
    
    # Retimer 0, 1, 2, 3, 4, 6, 7 combined (only for H100/H200 products)
    retimer_0_1_2_3_4_6_7_file = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.bin,.rom,.fw,.img',
        }),
        label='Retimer 0, 1, 2, 3, 4, 6, 7 Firmware',
        help_text='Upload firmware file for Retimers 0, 1, 2, 3, 4, 6, and 7 (same file will be used for all seven)'
    )
    
    def __init__(self, *args, product_type=None, **kwargs):
        """Initialize form and hide retimer fields for B200/B300 products"""
        super().__init__(*args, **kwargs)
        
        # Hide retimer fields for B200/B300 products
        if product_type and product_type.startswith(('B200', 'B300')):
            if 'retimer_5_file' in self.fields:
                del self.fields['retimer_5_file']
            if 'retimer_0_1_2_3_4_6_7_file' in self.fields:
                del self.fields['retimer_0_1_2_3_4_6_7_file']
    
    def clean(self):
        """Validate that at least one file is uploaded"""
        cleaned_data = super().clean()
        
        # Check if at least one file was uploaded
        has_file = any(
            cleaned_data.get(field_name)
            for field_name in self.fields.keys()
            if field_name.endswith('_file')
        )
        
        if not has_file:
            raise forms.ValidationError('Please upload at least one firmware file')
        
        return cleaned_data
    