#!/usr/bin/python

import sys
import subprocess
import argparse
from typing import List, Dict, Optional
import os
import hashlib
import pickle
import time
from pathlib import Path
import math
import yaml
from functools import partial

from utils import CACHE_FILE, JOURNAL_DIR, hash_journal_dir, load_cache, save_cache, run_hledger_command, parse_hledger_output, load_tax_params, load_hledger_aliases, load_business_expenses, load_home_office_info, load_filing_status, load_additional_federal_deduction


def compute_interest(year: int) -> float:
    """
    Compute the total mortgage interest paid for the given year, using either per-year override, hledger account, or amortization formula as specified in personal.yaml. If no option is provided, return 0.0.
    """
    with open("hledger_parameters/personal.yaml", "r") as f:
        params = yaml.safe_load(f)
    # Option 1: Per-year override
    if "interest_by_year" in params and str(year) in params["interest_by_year"]:
        return params["interest_by_year"][str(year)]
    # Option 2: Use hledger account
    if "interest_account" in params:
        return run_hledger_command(["bal", params["interest_account"]], year)
    # Option 3: Use amortization formula
    principal = params.get("principal")
    monthly_rate = params.get("monthly_rate")
    payment = params.get("payment")
    start_year = params.get("start_year")
    if None not in (principal, monthly_rate, payment, start_year):
        start_month = max(0, 12 * (year - start_year))
        end_month = start_month + 12
        def balance_after(m):
            if monthly_rate == 0:
                return principal - payment * m
            factor = pow(1 + monthly_rate, m)
            return principal * factor - payment * (factor - 1) / monthly_rate
        def interest_paid_until(m):
            total_paid = payment * m
            remaining_balance = balance_after(m)
            principal_reduction = principal - remaining_balance
            return total_paid - principal_reduction
        return interest_paid_until(end_month) - interest_paid_until(start_month)
    # Default: no valid option provided
    return 0.0


def compute_self_employment_tax(net_business_income: float) -> float:
    """
    Compute self-employment tax (Social Security + Medicare) for the given net business income.
    Returns the total SE tax amount.
    """
    # SE tax is 15.3% of 92.35% of net business income
    # This includes both Social Security (12.4%) and Medicare (2.9%)
    return net_business_income * 0.9235 * 0.029


def compute_investment_tax(investment_income: float, agi: float, year: int) -> float:
    """
    Compute Net Investment Income Tax (NIIT) for the given investment income.
    NIIT is only charged if AGI exceeds the threshold.
    Returns the investment tax amount.
    """
    # Load filing status from personal.yaml
    with open("hledger_parameters/personal.yaml", "r") as f:
        params = yaml.safe_load(f)
    filing_status = params.get("filing_status", "joint")
    
    # Load federal tax parameters to get NIIT threshold
    fed_params = load_tax_params(year)['federal'].get(filing_status)
    if fed_params is None:
        fed_params = load_tax_params(year)['federal'].get('joint')
    if fed_params is None:
        raise ValueError(f"No federal tax parameters found for filing status '{filing_status}' or 'joint'.")
    
    niit_threshold = fed_params.get('niit_threshold', 200000)  # Default to $200,000
    
    # NIIT is only charged if AGI exceeds the threshold
    if agi <= niit_threshold:
        return 0.0
    
    # If AGI exceeds threshold, tax is 3.8% of the lesser of:
    # 1. Net investment income, or
    # 2. AGI minus the threshold
    taxable_amount = min(investment_income, agi - niit_threshold)
    return 0.038 * max(taxable_amount, 0)


def compute_solo_401k_contribution(net_business_income: float, year: int) -> float:
    """
    Compute solo 401(k) contribution based on configuration in personal.yaml.
    Returns the contribution amount.
    """
    with open("hledger_parameters/personal.yaml", "r") as f:
        params = yaml.safe_load(f)
    
    # Get contribution configuration, default to maximize
    contribution_config = params.get("solo_401k_contribution", "maximize")
    
    # Calculate maximum allowed contribution (19.732% of net business income)
    max_contribution = net_business_income * 0.19732
    
    if contribution_config == "maximize":
        return max_contribution
    elif contribution_config == "none" or contribution_config == 0:
        return 0.0
    elif isinstance(contribution_config, (int, float)):
        # Treat as percentage of maximum (0-100)
        percentage = float(contribution_config) / 100.0
        return max_contribution * percentage
    else:
        # Default to maximize if invalid configuration
        return max_contribution


def compute_social_security_tax(w2_medicare: float, net_business_income: float, ss_max: float, soc_tax_paid: float, year: int) -> float:
    """
    Compute additional Social Security tax beyond the standard withholding.
    Returns the extra SS tax amount.
    """
    # Load filing status from personal.yaml
    with open("hledger_parameters/personal.yaml", "r") as f:
        params = yaml.safe_load(f)
    filing_status = params.get("filing_status", "joint")
    
    # Social Security tax is 12.4% (6.2% employee + 6.2% employer) on wages up to ss_max
    # For self-employed, it's the full 12.4% on self-employment income up to ss_max
    
    # Calculate total Social Security tax owed
    # W2 wages: 12.4% up to ss_max
    # For joint filing, multiply ss_max by 2 (both spouses can contribute up to ss_max)

    # assumes that both spouses are over the limit
    if filing_status == "joint":
        ss_max = ss_max * 2
    w2_ss_tax = min(w2_medicare * 0.124, ss_max)
    # Self-employment income: 12.4% on 92.35% of net business income up to ss_max
    # But only on the portion that hasn't already been taxed through W2
    remaining_ss_limit = max(0, ss_max - w2_ss_tax)
    print(f"remaining_ss_limit: {remaining_ss_limit}")
    se_ss_tax = min(net_business_income * 0.9235 * 0.124, remaining_ss_limit) 
    
    total_ss_tax_owed = w2_ss_tax + se_ss_tax
    # Calculate additional Social Security tax owed (what should be paid minus what was paid)
    ss_extra = total_ss_tax_owed - soc_tax_paid
    return -ss_extra


def compute_medicare_tax(w2_medicare: float, net_business_income: float, med_tax_paid: float, year: int) -> float:
    """
    Compute additional Medicare tax beyond the standard withholding.
    Returns the extra Medicare tax amount.
    """
    # Load filing status from personal.yaml
    with open("hledger_parameters/personal.yaml", "r") as f:
        params = yaml.safe_load(f)
    filing_status = params.get("filing_status", "single")
    
    # Load federal tax parameters to get Medicare threshold
    fed_params = load_tax_params(year)['federal'].get(filing_status)
    if fed_params is None:
        fed_params = load_tax_params(year)['federal'].get('joint')
    if fed_params is None:
        raise ValueError(f"No federal tax parameters found for filing status '{filing_status}' or 'joint'.")
    
    threshold = fed_params.get('medicare_threshold', 200000)  # Default to $200,000

    medicare_tax = 0.0145 * w2_medicare  # medicare on self-employment income in self_employment_tax
    # Additional tax on W2 wages over threshold
    medicare_extra = max(0.0, w2_medicare + net_business_income * 0.9235 - threshold) * 0.009
    
    # Total additional Medicare tax
    total = medicare_tax + medicare_extra 
    
    # Subtract what's already been paid
    return max(total - med_tax_paid, 0.0)


def compute_bracket_tax(taxable_income: float, brackets: list) -> float:
    """
    Compute tax owed given a list of tax brackets and taxable income.
    Brackets should be a list of dicts with 'threshold' and 'rate', sorted ascending.
    """
    tax = 0.0
    prev_threshold = 0.0
    for i, bracket in enumerate(brackets):
        threshold = bracket['threshold']
        rate = bracket['rate']
        # For the last bracket, apply rate to all remaining income
        if i + 1 == len(brackets):
            tax += (taxable_income - threshold) * rate if taxable_income > threshold else 0
        else:
            next_threshold = brackets[i+1]['threshold']
            if taxable_income > threshold:
                taxed_amount = min(taxable_income, next_threshold) - threshold
                tax += taxed_amount * rate
    return max(tax, 0.0)

def compute_taxes(year: int):
    """
    Compute and print the tax summary for the given year.
    """
    params = load_tax_params(year)
    filing_status = load_filing_status()
    # Federal and CA params for the selected status
    fed_params = params['federal'].get(filing_status)
    if fed_params is None:
        fed_params = params['federal'].get('joint')
    if fed_params is None:
        raise ValueError(f"No federal tax parameters found for filing status '{filing_status}' or 'joint'.")
    ca_params = params['ca'].get(filing_status)
    if ca_params is None:
        ca_params = params['ca'].get('joint')
    if ca_params is None:
        raise ValueError(f"No CA tax parameters found for filing status '{filing_status}' or 'joint'.")
    fed_brackets = fed_params['brackets']
    fed_sd = fed_params['standard_deduction']
    ss_max = fed_params['ss_max']
    ca_brackets = ca_params['brackets']
    ca_sd = ca_params['standard_deduction']
    ca_surcharges = ca_params.get('surcharges', [])
    fed_surcharges = fed_params.get('surcharges', [])

    INTEREST = compute_interest(year)
    additional_deduction = load_additional_federal_deduction()

    # business_expenses = load_business_expenses()  # Removed - using aliases.yaml instead
    home_office = load_home_office_info()
    # Hledger queries (unchanged aliases and accounts)
    aliases = load_hledger_aliases()
    groups = {k: v for k, v in aliases.items() if k not in ["queries"]}
    queries = aliases["queries"]
    def build_accounts(q):
        result = []
        # Add all items in accounts (as strings)
        for acct in q.get("accounts", []):
            # If acct is a dict (from YAML unquoted key), convert to string
            if isinstance(acct, dict):
                for k, v in acct.items():
                    if v is None:
                        result.append(str(k) + ':')
                    else:
                        result.append(str(k) + ':' + str(v))
            else:
                result.append(str(acct))
        act = str(result)
        # Add all items from each group in remove_groups
        for group in q.get("remove_groups", []):
            for acct in groups.get(group, []):
                result.append(f"{str(acct)}")
        # Add --alias <alias>=xyz for each exclude_account
        for alias in q.get("exclude_accounts", []):
            result.append("--alias")
            result.append(f"{alias}=xyz")
        return result
    def hledger_query(query_key):
        q = queries.get(query_key, {})
        accounts = build_accounts(q)
        return run_hledger_command(accounts, year=year)
    def hledger_query_no_year(query_key):
        q = queries.get(query_key, {})
        accounts = build_accounts(q)
        accounts = [f"{acct}:{year}" for acct in accounts]  # <-- append year to each account
        return run_hledger_command(accounts)
    w2 = hledger_query("w2")
    w2_medicare = hledger_query("w2_medicare")
    w2_ca = hledger_query("w2_ca")
    total_inc = hledger_query("total_inc")
    dividend_longterm = hledger_query("dividend_longterm")
    dividend_shortterm = hledger_query("dividend_shortterm")
    dividend_shortterm_state = hledger_query("dividend_shortterm_state")
    dividend_qualified = hledger_query("dividend_qualified")
    capital_gain_longterm = hledger_query("capital_gain_longterm")
    capital_gain_shortterm = hledger_query("capital_gain_shortterm")
    loss = hledger_query("loss")
    interest = hledger_query("interest")
    interest_state = hledger_query("interest_state")
    fed_tax_paid = hledger_query_no_year("fed_tax_paid")
    soc_tax_paid = hledger_query_no_year("soc_tax_paid")
    med_tax_paid = hledger_query_no_year("med_tax_paid")
    state_tax_paid = hledger_query_no_year("state_tax_paid")
    # Calculate home office expenses using accounts from personal.yaml
    home_office_expenses = 0.0
    for acct in home_office.get("accounts", []):
        home_office_expenses += run_hledger_command([acct], year=year)
    
    business_expenses = 0.0
    for acct in queries.get("business_expenses", {}).get("accounts", []):
        business_expenses += run_hledger_command([acct], year=year)
    foreign_credit = hledger_query("foreign_credit")

    # Perform calculations using extracted functions
    home_deduct = home_office_expenses * home_office["deduction_rate"]
    ded = home_deduct + INTEREST * home_office["deduction_rate"] + home_office["fixed_deduction"]
    net_biz = total_inc - w2 - ded - business_expenses
    
    # Calculate taxes using extracted functions
    solo_cont = compute_solo_401k_contribution(net_biz, year)
    se_tax = compute_self_employment_tax(net_biz)
    inv_income = interest + dividend_shortterm + dividend_longterm + capital_gain_shortterm + capital_gain_longterm - loss
    
    # Calculate AGI for NIIT threshold check
    agi = w2 + interest + net_biz + (dividend_shortterm + capital_gain_shortterm) - loss - se_tax/2 - solo_cont
    inv_tax = compute_investment_tax(inv_income, agi, year)
    ss_extra = compute_social_security_tax(w2_medicare, net_biz, ss_max, soc_tax_paid, year)
    medicare_extra = compute_medicare_tax(w2_medicare, net_biz, med_tax_paid, year)
    # Calculate federal taxable income
    fed_taxable_income = (w2 + interest + net_biz + (dividend_shortterm+capital_gain_shortterm) - loss
                   - se_tax/2 - solo_cont - fed_sd - additional_deduction - 0.2*dividend_qualified)
    tax_liability = compute_bracket_tax(fed_taxable_income, fed_brackets) + 0.2 * (dividend_longterm + capital_gain_longterm)
    total_tax = tax_liability + inv_tax - ss_extra + se_tax + medicare_extra
    total_tax = max(total_tax, 0.0)
    owed = total_tax - (fed_tax_paid) - foreign_credit
    ca_mod_inc = (w2_ca + interest_state + net_biz +
                  (dividend_shortterm_state + capital_gain_shortterm) - loss - se_tax/2 - solo_cont +
                  dividend_longterm + capital_gain_longterm - ca_sd)
    # Generalized surcharge logic for CA and FEDERAL
    def compute_surcharges(taxable_income, surcharges):
        total = 0.0
        for s in surcharges or []:
            threshold = s.get('threshold', 0)
            rate = s.get('rate', 0)
            total += rate * max(taxable_income - threshold, 0.0)
        return total
    ca_tax = compute_bracket_tax(ca_mod_inc, ca_brackets)
    ca_owed = compute_surcharges(ca_mod_inc, ca_surcharges) + ca_tax - state_tax_paid

    # Output summary
    print("="*64)
    print(f"Tax Summary {year}")
    print("="*64)
    print(f"    W2 Wages (Line 1)\t\t\t\t${w2:,.2f}")
    print(f"    Interest (Line 2b)\t\t\t\t${interest:,.2f}")
    print(f"    State Interest\t\t\t\t${interest_state:,.2f}")
    print(f"        Non-Qualified Dividends\t\t\t\t${dividend_shortterm:,.2f}")
    print(f"        Short-Term Capital Gain\t\t\t\t${capital_gain_shortterm:,.2f}")
    print(f"    Short-term total\t\t\t\t${(dividend_shortterm+capital_gain_shortterm):,.2f}")
    print(f"        Qualified Dividends (Line 3a)\t\t\t${dividend_longterm:,.2f}")
    print(f"        Long-term Capital Gains\t\t\t\t${capital_gain_longterm:,.2f}")
    print(f"    Long-term total\t\t\t\t${(dividend_longterm+capital_gain_longterm):,.2f}")
    print(f"    Loss to offset income\t\t\t${loss:,.2f}")
    print(f"        Business Income\t\t\t\t\t${(total_inc - w2):,.2f}")
    print(f"        Home Office Deduction\t\t\t\t${ded:,.2f}")
    print(f"        Business Expenses\t\t\t\t${business_expenses:,.2f}")
    print(f"    Net Business Income (Line 8)\t\t${net_biz:,.2f}")
    print(f"    " + "-"*83)
    total_income = w2 + interest + dividend_shortterm + capital_gain_shortterm + dividend_longterm + capital_gain_longterm - loss + net_biz
    print(f"    Total (Line 9)\t\t\t\t${total_income:,.2f}")
    print(f"    Line 10\t\t\t\t\t${(se_tax/2 + solo_cont):,.2f}")
    print(f"    Line 14\t\t\t\t\t${(fed_sd + additional_deduction + 0.2*dividend_qualified):,.2f}")
    ti = (total_income - se_tax/2 - solo_cont - fed_sd - additional_deduction - 0.2*dividend_qualified)
    print(f"    Line 15\t\t\t\t\t${ti:,.2f}")
    print(f"    " + "-"*83)
    print(f"    Final tax bill\t\t\t\t${tax_liability:,.2f}")
    print(f"    Self-Employment Tax\t\t\t\t${se_tax:,.2f}")
    print(f"    Investment Tax (NIIT)\t\t\t${inv_tax:,.2f}")
    print(f"    Extra Social Security Tax\t\t\t${ss_extra:,.2f}")
    print(f"    Extra Medicare Tax\t\t\t\t${medicare_extra:,.2f}")
    print(f"    Foreign Tax Credit\t\t\t\t${foreign_credit:,.2f}")
    print(f"    Total Tax Due (Line 24 minus credits)\t${total_tax:,.2f}")
    print(f"    Tax Deposited (Line 25a + 26)\t\t${fed_tax_paid:,.2f}")
    print(f"    " + "-"*83)
    print(f"    Total Federal Owed\t\t\t\t${owed:,.2f}")
    print(f"    Total CA Owed\t\t\t\t${ca_owed:,.2f}")
    print(f"    Max Solo 401(k) Contribution\t\t${solo_cont:,.2f}")
    print("="*64)
    print("Disclaimer: This assumes standard deduction, etc. Values are computed as per the script logic.")

def main():
    parser = argparse.ArgumentParser(description="Compute tax summaries for given year(s).")
    parser.add_argument('years', type=int, nargs='+', help='Year(s) to compute taxes for')
    args = parser.parse_args()
    for year in args.years:
        compute_taxes(year)

if __name__ == "__main__":
    main()

