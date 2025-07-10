# Tax Calculator

A Python-based tax calculation tool that helps compute federal and California state taxes for individuals with various income sources including W2 wages, self-employment income, investment income, and business deductions.

## Features

- **Multi-year support**: Calculate taxes for any year with configurable tax parameters
- **Multiple income sources**: W2 wages, self-employment income, dividends, capital gains, interest
- **Business deductions**: Home office deductions, business expenses, solo 401(k) contributions
- **Tax calculations**: Federal and California state taxes with proper bracket calculations
- **Specialized taxes**: Self-employment tax, Medicare tax, Social Security tax, Net Investment Income Tax (NIIT)
- **Hledger integration**: Uses hledger for financial data queries
- **Configurable**: All tax parameters and personal settings stored in YAML files

## Prerequisites

- Python 3.6+
- [hledger](https://hledger.org/) (for financial data queries)
- PyYAML

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd taxes
```

2. Install Python dependencies:
```bash
pip install pyyaml
```

3. Configure your personal settings in `hledger_parameters/personal.yaml`:
   - Set your filing status (joint, single, head)
   - Configure your hledger journal directory path
   - Set up mortgage interest calculation
   - Configure home office deduction settings
   - Set solo 401(k) contribution preferences

4. Configure your hledger account aliases in `hledger_parameters/aliases.yaml`:
   - Map your actual hledger accounts to the expected query names
   - Configure business expense accounts
   - Set up tax payment accounts

5. Update tax parameters in `tax_parameters/`:
   - Federal tax brackets and thresholds in `FEDERAL/YYYY.yaml`
   - California tax brackets and thresholds in `CA/YYYY.yaml`

## Usage

### Basic Usage

Calculate taxes for a specific year:
```bash
python3 taxes.py 2024
```

Calculate taxes for multiple years:
```bash
python3 taxes.py 2023 2024 2025
```

### Configuration Files

#### `hledger_parameters/personal.yaml`
Contains personal configuration settings:
- `filing_status`: Tax filing status (joint, single, head)
- `journal_directory`: Path to your hledger journal files
- `solo_401k_contribution`: Solo 401(k) contribution strategy
- `additional_federal_deduction`: Additional federal deductions
- `interest_by_year`: Mortgage interest by year (optional)
- `home_office`: Home office deduction configuration

#### `hledger_parameters/aliases.yaml`
Maps hledger accounts to tax calculation queries:
- Income accounts (W2, dividends, capital gains, interest)
- Tax payment accounts
- Business expense accounts
- Foreign tax credit accounts

#### `tax_parameters/FEDERAL/YYYY.yaml` and `tax_parameters/CA/YYYY.yaml`
Tax brackets, thresholds, and rates for each year:
- Income tax brackets
- Standard deductions
- Social Security maximums
- Medicare thresholds
- NIIT thresholds
- State surcharges

## Example Output

```
================================================================
Tax Summary 2024
================================================================
    W2 Wages (Line 1)                                    $85,000.00
    Interest (Line 2b)                                     $2,500.00
    State Interest                                         $2,500.00
        Non-Qualified Dividends                            $1,200.00
        Short-Term Capital Gain                            $800.00
    Short-term total                                       $2,000.00
        Qualified Dividends (Line 3a)                      $3,500.00
        Long-term Capital Gains                            $2,000.00
    Long-term total                                        $5,500.00
    Loss to offset income                                  $0.00
        Business Income                                    $25,000.00
        Home Office Deduction                              $3,500.00
        Business Expenses                                  $5,000.00
    Net Business Income (Line 8)                          $16,500.00
    -----------------------------------------------------------------------------------
    Total (Line 9)                                        $111,000.00
    Line 10                                               $4,500.00
    Line 14                                               $15,000.00
    Line 15                                               $91,500.00
    -----------------------------------------------------------------------------------
    Final tax bill                                        $15,200.00
    Self-Employment Tax                                    $2,300.00
    Investment Tax (NIIT)                                  $0.00
    Extra Social Security Tax                              $0.00
    Extra Medicare Tax                                     $0.00
    Foreign Tax Credit                                     $0.00
    Total Tax Due (Line 24 minus credits)                 $17,500.00
    Tax Deposited (Line 25a + 26)                         $16,000.00
    -----------------------------------------------------------------------------------
    Total Federal Owed                                     $1,500.00
    Total CA Owed                                          $800.00
    Max Solo 401(k) Contribution                           $3,250.00
================================================================
Disclaimer: This assumes standard deduction, etc. Values are computed as per the script logic.
```

## Important Disclaimers

⚠️ **This tool is for educational and planning purposes only. It is not a substitute for professional tax advice.**

- The calculations are based on current tax law understanding but may not reflect all tax situations
- Tax laws change frequently - verify all calculations with current IRS and state tax authorities
- Consult with a qualified tax professional for your specific tax situation
- The tool makes certain assumptions (e.g., standard deduction) that may not apply to all taxpayers
- Results should be verified against official tax forms and professional tax software

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

If you encounter any issues or have questions, please open an issue on GitHub. However, please note that this is not a professional tax advisory service. 