"""
Standalone Python script equivalent to notebooks/demo.ipynb

This script replicates all functionality from the demo notebook:
1. Data processing pipeline (load, tag, clean, combine, label, analyze)
2. Chat functionality for asking questions about the data

Run this script to execute the full pipeline and interact with the data.
"""

# ============================================================================
# SECTION 1: IMPORTS AND DEPENDENCIES
# ============================================================================

import asyncio
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Iterable, Literal
import pickle
import sys

import pandas as pd
pd.options.mode.copy_on_write = True
from dotmap import DotMap
from matplotlib import pyplot as plt
from pydantic import BaseModel
import tqdm.asyncio as _tqdm_asyncio
from tqdm import tqdm

# OpenAI imports
try:
    from openai import AsyncOpenAI, OpenAI
    ACLIENT = AsyncOpenAI()
    CLIENT = OpenAI()
except Exception:
    ACLIENT = None
    CLIENT = None


# ============================================================================
# SECTION 2: CONFIGURATION
# ============================================================================

# Paths
ROOT_DIR = Path(__file__).resolve().parent
INPUT_DATA_DIR = ROOT_DIR / 'data' / 'input'
OUTPUT_DATA_DIR = ROOT_DIR / 'data' / 'output'

# Chart configuration
CATEGORY_MIN = 500
VENDOR_MIN = 500

# Column name mappings
COLUMNS = {
    'Date': 'date',
    'Transaction Date': 'date',
    'Order Date': 'date',
    0: 'date',
    'Description': 'description',
    'Product Name': 'description',
    3: 'description',
    'Amount': 'amount',
    'Total Owed': 'amount',
    1: 'amount'
}

# Row exclusion indicators
ROW_EXCLUSION_INDICATORS = 'Mobile Payment|Beginning balance|EPAY ID'

# Vendor dictionary for known vendors
VENDOR_DICT = {
    'ALLY AUTO': {'vendor': 'Ally Auto', 'category': 'Automotive'},
    'CITY OF DALLAS UTILITIES': {'vendor': 'City of Dallas', 'category': 'Utilities'},
    'GOOGLE STORAGE': {'vendor': 'Google', 'category': 'Subscriptions'},
    'GREYSTAR': {'vendor': 'Greystar', 'category': 'Rent'},
    'NETFLIX': {'vendor': 'Netflix', 'category': 'Subscriptions'},
    'PLANET FITNESS': {'vendor': 'Planet Fitness', 'category': 'Gym & Fitness'},
    'PLNT FITNESS': {'vendor': 'Planet Fitness', 'category': 'Gym & Fitness'},
    'SPOTIFY': {'vendor': 'Spotify', 'category': 'Subscriptions'},
    'TXU ENERGY': {'vendor': 'TXU Energy', 'category': 'Utilities'},
    'WSJ DIGITAL': {'vendor': 'Wall Street Journal', 'category': 'Subscriptions'}
}

# Expense categories
ExpenseCategory = Literal[
    'Automotive',
    'Baby & Child',
    'Books',
    'Clothing & Accessories',
    'Electronics & Accessories',
    'General',
    'Groceries',
    'Gym & Fitness',
    'Health & Personal Care',
    'Home',
    'Office Supplies',
    'Other Food & Beverage',
    'Pet Supplies',
    'Sports & Recreation',
    'Other'
]

# OpenAI configuration
MODEL = 'gpt-5-mini'
SERVICE_TIER = 'priority'

PRODUCT_LABELING_INSTRUCTIONS = '''The user will provide an Amazon 
    product name. Return the most fitting category from the supplied
    JSON schema.'''

PAYMENT_LABELING_INSTRUCTIONS = '''The user will provide a transaction
    description from a bank statement. Return the common short brand 
    name of the counterparty and the most fitting category from the 
    supplied JSON schema.'''

CHAT_INSTRUCTIONS = '''Provide a direct, terse answer to the user's
    questions about the expense data in the supplied file using the 
    Python tool (a.k.a. the Code Interpreter tool) as necessary. Do not
    offer to share created files. Do not mention the supplied file or
    its structure (e.g. its columns); from the user's perspective, 
    these are implementation details.'''


# ============================================================================
# SECTION 3: UTILITY CLASSES AND HELPERS
# ============================================================================

class ProgressBar:
    """A minimal ProgressBar wrapper for asynchronous operations."""
    @staticmethod
    async def gather(*args, **kwargs):
        return await _tqdm_asyncio.tqdm_asyncio.gather(*args, **kwargs)

    @staticmethod
    def as_completed(*args, **kwargs):
        return _tqdm_asyncio.tqdm_asyncio.as_completed(*args, **kwargs)


class CategoryResponse(BaseModel):
    category: ExpenseCategory


class DualResponse(BaseModel):
    vendor: str
    category: ExpenseCategory


def convert_to_decimal(value):
    """Convert value to Decimal with 2 decimal places."""
    cent = Decimal('0.01')
    return Decimal(value).quantize(cent)


# ============================================================================
# SECTION 4: DATA LOADING
# ============================================================================

def load_data():
    """
    Load Jack and Jill's checking, credit card, and Amazon data and 
    return a dictionary of DataFrames.
    
    All expected data files must be present in the correct directory
    with the correct names.
    """
    amzn = pd.read_csv(INPUT_DATA_DIR / 'amazon.csv', header=0)
    jack_ch = pd.read_csv(INPUT_DATA_DIR / 'jack_checking.csv', header=None)
    jack_cc = pd.read_csv(INPUT_DATA_DIR / 'jack_credit_card.csv', header=0)
    jill_ch = pd.read_csv(INPUT_DATA_DIR / 'jill_checking.csv', header=0)
    jill_cc = pd.read_csv(INPUT_DATA_DIR / 'jill_credit_card.csv', header=4)
    
    data = {
        'amzn': amzn,
        'jack_ch': jack_ch,
        'jack_cc': jack_cc,
        'jill_ch': jill_ch,
        'jill_cc': jill_cc
    }
    
    return data


# ============================================================================
# SECTION 5: DATA TAGGING
# ============================================================================

def tag(data):
    """
    Add 'account' and 'spender' columns with the appropriate values.
    """
    for account in data:
        data[account]['account'] = account
        data[account]['spender'] = 'Jack' if 'jack' in account else 'Jill'
    
    return data


# ============================================================================
# SECTION 6: DATA CLEANING
# ============================================================================

def rename_columns(data):
    """Rename the necessary columns in each data table."""
    for account in data:
        data[account] = data[account].rename(columns=COLUMNS)
    return data


def filter_amazon(table):
    """
    Isolate Amazon products purchased exclusively with Jill's Visa 
    credit card ending in 1234.
    """
    filter = table['Payment Instrument Type'] == 'Visa - 1234'
    table = table[filter]
    return table


def filter_cc(table):
    """Remove unnecessary rows from both credit card accounts."""
    filter = ~table['description'].str.contains(ROW_EXCLUSION_INDICATORS)
    table = table[filter]
    return table


def filter_rows(data):
    """
    Remove unnecessary rows from both credit card accounts and isolate
    Amazon products purchased exclusively with Jill's Visa credit card
    ending in 1234.
    """
    for account, table in data.items():
        if account == 'amzn':
            data[account] = filter_amazon(table)
        elif 'cc' in account:
            data[account] = filter_cc(table)
    return data


def drop_columns(data):
    """
    Drop all columns except date, amount, description, account, and spender.
    """
    for account, table in data.items():
        data[account] = table[['date', 'amount', 'description', 'account', 'spender']]
    return data


def cast_date_dtype(data, account):
    """
    Cast the dtype of the 'amzn' date column to datetime and all other
    date columns to date.
    """
    if account == 'amzn':
        data[account]['date'] = pd.to_datetime(data[account]['date'])
    else:
        data[account]['date'] = pd.to_datetime(data[account]['date']).dt.date
    return data


def cast_amount_dtype(data, account):
    """Cast the amount column of data[account] to Decimal."""
    data[account]['amount'] = data[account]['amount'].apply(convert_to_decimal)
    return data


def cast_dtypes(data):
    """
    Cast the dtype of the 'amzn' date column to datetime, all other
    date columns to date, and all amount columns to Decimal.
    """
    for account in data:
        data = cast_date_dtype(data, account)
        data = cast_amount_dtype(data, account)
    return data


def clean(data):
    """
    Remove unnecessary rows and columns and set the names and dtypes
    of the remaining columns.
    """
    data = rename_columns(data)
    data = filter_rows(data)
    data = drop_columns(data)
    data = cast_dtypes(data)
    return data


# ============================================================================
# SECTION 7: DATA COMBINING - MATCHER CLASS
# ============================================================================

class Order:
    """
    Create a new Order instance for matching Amazon products to payments.
    """
    
    def __init__(self, matcher, order_id):
        self.date = order_id.date()
        self.pmts = DotMap({
            'candidates': self.identify_candidates(matcher),
            'matched': pd.Index([], dtype='int64')
        })
        self.prods = DotMap({
            'unmatched': Order.extract_products(matcher, order_id),
            'matched': pd.Index([], dtype='int64')
        })
        self.counter = Counter({
            'match_all_products': 0,
            'match_single_products': 0,
            'match_product_combos': 0
        })
    
    def match(self):
        """
        Identify the matching payments and products associated with a 
        single Amazon order.
        """
        # Step 1
        if len(self.pmts.candidates) == 0:
            return None
        else:
            self.match_all_products()
        
        # Step 2
        if len(self.prods.unmatched) < 2:
            return None
        else:
            self.match_single_products()
        
        # Step 3
        if len(self.prods.unmatched) < 4:
            return None
        else:
            self.match_product_combos()
    
    def match_all_products(self):
        prods_amt = self.prods.unmatched['amount'].sum()
        for pmt_idx, pmt_amt in self.pmts.candidates['amount'].items():
            if pmt_amt == prods_amt:
                self.record_match(
                    pd.Index([pmt_idx]),
                    self.prods.unmatched.index,
                    'match_all_products'
                )
                break
    
    def match_single_products(self):
        for pmt_idx, pmt_amt in self.pmts.candidates['amount'].items():
            for prod_idx, prod_amt in self.prods.unmatched['amount'].items():
                if prod_amt == pmt_amt:
                    self.record_match(
                        pd.Index([pmt_idx]),
                        pd.Index([prod_idx]),
                        'match_single_products'
                    )
                    if len(self.prods.unmatched) > 1:
                        self.match_all_products()
                    break
            if len(self.prods.unmatched) == 0:
                break
    
    def match_product_combos(self):
        initial_prod_count = len(self.prods.unmatched)
        for combo_length in self.generate_combo_lengths(initial_prod_count):
            self.match_combos_of_length(combo_length)
            if len(self.prods.unmatched) <= combo_length:
                break
    
    @staticmethod
    def generate_combo_lengths(initial_prod_count):
        return range(2, initial_prod_count // 2 + 1)
    
    def match_combos_of_length(self, combo_length):
        for pmt_idx, pmt_amt in self.pmts.candidates['amount'].items():
            for combo in self.generate_combinations(combo_length):
                combo_amt = self.calculate_combo_amount(combo)
                if combo_amt == pmt_amt:
                    self.record_match(
                        pd.Index([pmt_idx]),
                        pd.Index(combo),
                        'match_product_combos'
                    )
                    if len(self.prods.unmatched) >= combo_length:
                        self.match_all_products()
                    break
            if len(self.prods.unmatched) <= combo_length:
                break
    
    def generate_combinations(self, combo_length) -> Iterable[tuple[int]]:
        return combinations(self.prods.unmatched.index, combo_length)
    
    def calculate_combo_amount(self, combo):
        return self.prods.unmatched.loc[list(combo), 'amount'].sum()
    
    def record_match(self, payment_index: pd.Index, product_index: pd.Index, function):
        self.pmts.matched = self.pmts.matched.append(payment_index)
        self.pmts.candidates = self.pmts.candidates.drop(index=payment_index)
        self.prods.matched = self.prods.matched.append(product_index)
        self.prods.unmatched = self.prods.unmatched.drop(index=product_index)
        self.counter[function] += 1
    
    def identify_candidates(self, matcher, max_delay=3) -> pd.DataFrame:
        payments = matcher.pmts.filtered
        filter = payments['date'].between(self.date, self.date + timedelta(days=max_delay))
        return payments[filter]
    
    @staticmethod
    def extract_products(matcher, order_id) -> pd.DataFrame:
        products = matcher.prods.original
        products = products[products['date'] == order_id]
        return products


class Matcher:
    """
    Create a new Matcher instance for matching Amazon payments with products.
    """
    
    def __init__(self, payments, products, path):
        self.pmts = DotMap({
            'original': payments,
            'filtered': payments[payments['description'].str.contains('AMAZON')],
            'matched': pd.Index([], dtype='int64'),
            'unmatched': pd.Index([], dtype='int64')
        })
        
        self.prods = DotMap({
            'original': products,
            'order_ids': products['date'].unique(),
            'matched': pd.Index([], dtype='int64'),
            'unmatched': pd.Index([], dtype='int64')
        })
        
        self.counter = Counter({
            'match_all_products': 0,
            'match_single_products': 0,
            'match_product_combos': 0
        })
        
        self.integrated_data = pd.DataFrame({})
        self.path = path / 'matcher.pkl'
    
    def match(self):
        """
        Replace bank records of Amazon payments with the more detailed 
        product data to enable more meaningful expense classification.
        """
        self.process_orders()
        self.compile_results()
        self.save()
    
    def process_orders(self):
        for id in tqdm(self.prods.order_ids, desc='Matching Amazon Orders', unit='order', bar_format='{l_bar}{bar} {n_fmt}/{total_fmt} [{elapsed}]'):
            order = Order(self, id)
            order.match()
            self.update(order)
    
    def update(self, order):
        self.pmts.matched = self.pmts.matched.append(order.pmts.matched)
        self.prods.matched = self.prods.matched.append(order.prods.matched)
        self.prods.unmatched = self.prods.unmatched.append(order.prods.unmatched.index)
        self.counter += order.counter
    
    def compile_results(self):
        self.integrated_data = self.integrate_data()
        self.pmts.unmatched = self.isolate_unmatched_payments()
    
    def integrate_data(self):
        pmts_minus_matches = self.pmts.original.drop(index=self.pmts.matched)
        matched_prods_to_add = self.prods.original.loc[self.prods.matched]
        integrated_data = pd.concat([pmts_minus_matches, matched_prods_to_add], ignore_index=True)
        integrated_data['date'] = pd.to_datetime(integrated_data['date']).dt.date
        return integrated_data
    
    def isolate_unmatched_payments(self):
        return self.pmts.filtered.drop(index=self.pmts.matched).index
    
    def save(self):
        with open(self.path, 'wb') as f:
            pickle.dump(self, f)


def integrate_product_data(payments, products):
    """
    Replace matchable Amazon payments with corresponding products.
    """
    matcher = Matcher(payments, products, OUTPUT_DATA_DIR)
    matcher.match()
    return matcher.integrated_data


def combine_ch_and_cc_data(data):
    """Combine all checking and credit card data."""
    return pd.concat(
        [
            data['jack_ch'],
            data['jack_cc'],
            data['jill_ch'],
            data['jill_cc']
        ],
        ignore_index=True
    )


def combine(data):
    """
    Swap Amazon payments in Jill's credit card data with more detailed
    product purchase data and then combine all checking and credit card
    data.
    """
    data['jill_cc'] = integrate_product_data(data['jill_cc'], data['amzn'])
    data['combined'] = combine_ch_and_cc_data(data)
    return data


# ============================================================================
# SECTION 8: DATA LABELING
# ============================================================================

def vendor_is_known(row, table):
    """
    Return `True` if the row description contains a familiar vendor
    code and `False` if not.
    """
    description = table.loc[row, 'description']
    vendor_codes = VENDOR_DICT.keys()
    for code in vendor_codes:
        if code in description:
            return True
    return False


def get_known_labels(row, table):
    """Get pre-defined labels for a payment to a familiar vendor."""
    description = table.loc[row, 'description']
    vendor_codes = VENDOR_DICT.keys()
    for code in vendor_codes:
        if code in description:
            labels = VENDOR_DICT[code]
            return labels


async def make_product_labels(row, table):
    """Label one row of Amazon product data using the OpenAI API."""
    product_name = table.loc[row, 'description']
    
    instructions = PRODUCT_LABELING_INSTRUCTIONS
    
    response = await ACLIENT.responses.parse(
        model=MODEL,
        input=product_name,
        instructions=instructions,
        text_format=CategoryResponse,
        service_tier=SERVICE_TIER
    )
    
    labels = {
        'vendor': 'Amazon',
        'category': response.output_parsed.category,
        'llm_category': 1
    }
    
    return labels


async def make_labels_with_OpenAI(row, table):
    """Label one row of payment data using the OpenAI API."""
    description = table.loc[row, 'description']
    
    instructions = PAYMENT_LABELING_INSTRUCTIONS
    
    response = await ACLIENT.responses.parse(
        model=MODEL,
        input=description,
        instructions=instructions,
        text_format=DualResponse,
        service_tier=SERVICE_TIER
    )
    
    labels = {
        'vendor': response.output_parsed.vendor,
        'category': response.output_parsed.category,
        'llm_vendor': 1,
        'llm_category': 1
    }
    
    return labels


async def make_payment_labels(row, table):
    """
    Label one row of payment data.
    
    This function returns pre-defined labels for familiar transactions
    and makes new labels for other transactions with the OpenAI API.
    """
    if vendor_is_known(row, table):
        labels = get_known_labels(row, table)
    else:
        labels = await make_labels_with_OpenAI(row, table)
    
    return labels


def make_row_instructions(table):
    """Make a list with one labeling coroutine for each row in table."""
    row_instructions = []
    
    for row in table.index:
        if table.loc[row, 'account'] == 'amzn':
            row_instructions.append(make_product_labels(row, table))
        else:
            row_instructions.append(make_payment_labels(row, table))
    
    return row_instructions


async def process_asynchronously(row_instructions):
    """Process all coroutines in row_instructions asynchronously."""
    labels = await ProgressBar.gather(
        *row_instructions,
        desc='Labeling Rows with OpenAI',
        unit='row',
        bar_format='{l_bar}{bar} {n_fmt}/{total_fmt} [{elapsed}]'
    )
    return labels


def make_table_instructions(row_instructions):
    """
    Convert row_instructions into a function that contains all 
    asynchronous labeling operations for the source table.
    """
    def table_instructions():
        labels = asyncio.run(process_asynchronously(row_instructions))
        return labels
    
    return table_instructions


def make_labeling_instructions(table):
    """
    Make a function that contains all asynchronous labeling operations
    for table.
    """
    row_instructions = make_row_instructions(table)
    table_instructions = make_table_instructions(row_instructions)
    return table_instructions


def make_labels(instructions):
    """
    Make labels from instructions with the OpenAI API.
    
    This function executes all asynchronous labeling operations in a 
    new thread to avoid conflict with Jupyter Notebook event loops.
    """
    from concurrent.futures import ThreadPoolExecutor as JobManager
    with JobManager() as m:
        job = m.submit(instructions)
    
    labels = job.result()
    return labels


def apply_labels(all_labels, table):
    """Apply labels to table."""
    for row, row_labels in zip(table.index, all_labels):
        for column in row_labels:
            table.loc[row, column] = row_labels[column]
    
    return table


def save(table):
    """
    Save table as labeled_data.csv in the output data folder defined in
    the config module.
    """
    table.to_csv(OUTPUT_DATA_DIR / 'labeled_data.csv', index=False)


def label(data):
    """
    Label each row of data['combined'] and bind the result to 
    data['labeled'].
    
    This function adds the following columns:
        vendor: The transaction counterparty
        category: The transaction category
        llm_vendor: A binary flag that indicates that an LLM generated
        the corresponding value in the vendor column
        llm_category: A binary flag that indicates that an LLM  
        generated the corresponding value in the category column
    """
    instructions = make_labeling_instructions(data['combined'])
    labels = make_labels(instructions)
    data['labeled'] = apply_labels(labels, data['combined'])
    save(data['labeled'])
    
    return data


# ============================================================================
# SECTION 9: DATA ANALYSIS - STATISTICS
# ============================================================================

def show_time_period(table):
    """Display the dates of the earliest and latest transactions in table."""
    start_date = str(table['date'].min())
    end_date = str(table['date'].max())
    print('')
    print(f'Time Period: {start_date} to {end_date}')


def show_total_spend(table):
    """Print the sum of all expenses in the given table."""
    total_spend = table['amount'].sum()
    print('')
    print(f'Total Spending: ${total_spend:,.2f}')


def format_values(account_totals):
    """Format the values of account_totals as money."""
    return account_totals.map(lambda x: f'${x:,.2f}')


def remove_unnecessary_data(account_totals):
    """
    Remove the Series name, index name, and dtype from the 
    account_totals display.
    """
    return account_totals.to_string(header=False)


def format_account_totals(account_totals):
    """Format values and remove unnecessary data."""
    account_totals = format_values(account_totals)
    account_totals = remove_unnecessary_data(account_totals)
    return account_totals


def show_spend_by_account(table):
    """Print the sum of expenses by account."""
    grouped_table = table.groupby('account')
    account_totals = grouped_table['amount'].sum()
    formatted_totals = format_account_totals(account_totals)
    print('')
    print('Spending by Account:')
    print(formatted_totals)
    print('')


def show_stats(table):
    """Calculate and display total spending and spending by account."""
    show_total_spend(table)
    show_spend_by_account(table)


def save_summary(table):
    """
    Save summary statistics as CSV files in the output directory.
    Creates summary CSV files with formatted text matching the console output.
    """
    OUTPUT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get summary data
    start_date = str(table['date'].min())
    end_date = str(table['date'].max())
    total_spend = float(table['amount'].sum())
    grouped_table = table.groupby('account')
    account_totals = grouped_table['amount'].sum()
    
    # Create comprehensive summary with formatted text (matching console output)
    summary_lines = [
        f'Time Period: {start_date} to {end_date}',
        '',
        f'Total Spending: ${total_spend:,.2f}',
        '',
        'Spending by Account:',
    ]
    
    # Add account breakdown (formatted like console output)
    for account, amount in account_totals.items():
        formatted_amount = f'${float(amount):,.2f}'
        summary_lines.append(f'{account:12} {formatted_amount}')
    
    summary_lines.append('')
    
    # Save as CSV with single column containing the formatted text
    summary_df = pd.DataFrame({
        'Summary': summary_lines
    })
    summary_df.to_csv(OUTPUT_DATA_DIR / 'summary.csv', index=False)
    
    # Also create structured CSV file for data processing
    summary_stats = pd.DataFrame({
        'Metric': ['Start Date', 'End Date', 'Total Spending'],
        'Value': [start_date, end_date, f'${total_spend:,.2f}']
    })
    summary_stats.to_csv(OUTPUT_DATA_DIR / 'summary_stats.csv', index=False)
    
    print(f"\nSummary saved to:")
    print(f"  - {OUTPUT_DATA_DIR / 'summary.csv'} (formatted text)")
    print(f"  - {OUTPUT_DATA_DIR / 'summary_stats.csv'} (structured data)")


# ============================================================================
# SECTION 10: DATA ANALYSIS - CHARTS
# ============================================================================

def cast_amount_to_float(table):
    """Cast the dtype of table['amount'] to float."""
    table['amount'] = table['amount'].astype(float)
    return table


def sum_amount_by_group(table, grouping):
    """
    Group the rows in table by grouping and then sum 'amount' column 
    values.
    """
    return table.groupby(grouping)['amount'].sum()


def sort(data):
    """
    Sort rows in descending order with 'Other', if present, in the last
    position.
    """
    data = data.sort_values(ascending=False)
    
    if 'Other' in data.index:
        new_index = [*data.index.drop('Other'), 'Other']
        data = data.reindex(new_index)
    
    return data


def prepare_data(table, grouping):
    """
    Set the 'amount' column to a compatible dtype, sum amount by group,
    and sort the result.
    """
    data = cast_amount_to_float(table)
    data = sum_amount_by_group(table, grouping)
    data = sort(data)
    return data


def make_canvas(grouping):
    """Return a new, titled `Axes` object for plotting."""
    canvas = plt.subplot(111)
    canvas.set_title(f'Spending by {grouping.title()}')
    return canvas


def make_autopct_function(grouped_df):
    """
    Create a label formatting function to pass to the Matplotlib pie chart 
    method.
    """
    def autopct(wedge_percentage):
        total_dollar_value = grouped_df.sum()
        wedge_dollar_value = (wedge_percentage / 100) * total_dollar_value
        return f'${wedge_dollar_value:,.2f}\n({int(round(wedge_percentage)):d}%)'
    return autopct


def prepare_pie_elements(data, canvas):
    """Prepare pie chart elements for display."""
    canvas.pie(
        data,
        labels=data.index,
        autopct=make_autopct_function(data),
        startangle=90,
        counterclock=False
    )
    canvas.axis('equal')


def draw_bars(data, canvas):
    """Plot bars of data values on canvas from top to bottom."""
    data.plot(kind='barh', ax=canvas)
    canvas.invert_yaxis()


def remove_x_axis_labels(canvas):
    """Remove labels and ticks from the x axis of canvas."""
    canvas.set_xlabel(None)
    canvas.set_xticks([])
    canvas.tick_params(axis='x', bottom=False, labelbottom=False)


def add_bar_labels(data, canvas):
    """Label the value of each bar on canvas."""
    bars = canvas.containers[0]
    canvas.bar_label(
        bars,
        labels=[f'${v:,.2f}' for v in data.values],
        label_type='edge',
        padding=4
    )
    canvas.margins(x=0.2)


def set_labels(data, canvas):
    """Remove x axis labels and ticks and label each bar on canvas."""
    remove_x_axis_labels(canvas)
    add_bar_labels(data, canvas)


def prepare_bar_elements(data, canvas):
    """Plot and label bars on canvas."""
    draw_bars(data, canvas)
    set_labels(data, canvas)


def display_chart(table, grouping, chart_type):
    """
    Display a bar or pie chart of table data grouped by grouping.
    Also saves the chart as a PNG file in the output directory.
    """
    prepared_data = prepare_data(table, grouping)
    canvas = make_canvas(grouping)
    
    if chart_type == 'bar':
        prepare_bar_elements(prepared_data, canvas)
    elif chart_type == 'pie':
        prepare_pie_elements(prepared_data, canvas)
    else:
        raise ValueError(f"chart_type must be 'bar' or 'pie'; received {chart_type}.")
    
    # Save the chart as an image file
    OUTPUT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f'spending_by_{grouping}.png'
    filepath = OUTPUT_DATA_DIR / filename
    plt.savefig(filepath, dpi=300, bbox_inches='tight')
    
    # Also display the chart
    plt.show()


def merge_groups(table, grouping, min):
    """
    For all rows in any group with a total expense amount under min,
    change the value of the grouping column to "Other".
    """
    expense_totals = table.groupby(grouping)['amount'].sum()
    small_groups = expense_totals[expense_totals < min].index
    filter = table[grouping].isin(small_groups)
    table.loc[filter, grouping] = 'Other'
    return table


def show_spend_by_spender(table):
    """Display a pie chart of total expenses by spender."""
    display_chart(table, 'spender', 'pie')


def show_spend_by_category(table):
    """
    Display a pie chart of total expenses by category.
    
    Merge categories with fewer than min transactions.
    """
    table = merge_groups(table, 'category', CATEGORY_MIN)
    display_chart(table, 'category', 'pie')


def show_spend_by_vendor(table):
    """
    Display a bar chart of total expenses by vendor.
    
    Merge vendors with fewer than min transactions.
    """
    table = merge_groups(table, 'vendor', VENDOR_MIN)
    display_chart(table, 'vendor', 'bar')


def show_charts(table):
    """
    Display spending by spender and by category as pie charts and 
    spending by vendor as a bar chart.
    """
    show_spend_by_spender(table)
    show_spend_by_category(table)
    show_spend_by_vendor(table)


def analyze(data):
    """
    Display charts and statistics for the labeled expense data.
    """
    table = data['labeled']
    show_time_period(table)
    show_stats(table)
    save_summary(table)
    show_charts(table)


# ============================================================================
# SECTION 11: MAIN PIPELINE FUNCTION
# ============================================================================

def run():
    """
    Execute the complete data processing pipeline:
    1. Load data from CSV files
    2. Tag data with account and spender information
    3. Clean data (rename columns, filter rows, drop columns, cast dtypes)
    4. Combine data (integrate Amazon products, combine all accounts)
    5. Label data (add vendor and category using OpenAI API)
    6. Analyze data (show statistics and charts)
    """
    data = load_data()
    data = tag(data)
    data = clean(data)
    data = combine(data)
    data = label(data)
    analyze(data)


# ============================================================================
# SECTION 12: CHAT FUNCTIONALITY
# ============================================================================

def initiate_conversation():
    """Create and return a new OpenAI conversation."""
    return CLIENT.conversations.create()


def add_expense_file():
    """
    Upload labeled_data.csv to the OpenAI servers and return an OpenAI
    File object.
    """
    file_path = OUTPUT_DATA_DIR / 'labeled_data.csv'
    with open(file_path, 'rb') as f:
        return CLIENT.files.create(file=f, purpose='user_data')


def configure_python_tool(expense_file):
    """
    Configure the code interpreter tool for an OpenAI model to use to
    inspect expense_file.
    """
    config = [{
        'type': 'code_interpreter',
        'container': {
            'type': 'auto',
            'file_ids': [expense_file.id]
        }
    }]
    return config


class Chat:
    """
    Start a new conversation about the labeled expense data with the 
    OpenAI API.
    """
    
    def __init__(self):
        self.conversation = initiate_conversation()
        self.expense_file = add_expense_file()
        self.tool_config = configure_python_tool(self.expense_file)
        self.instructions = CHAT_INSTRUCTIONS
    
    def msg(self, message):
        """
        Send a new message and print the model's response.
        
        Context includes the labeled data and prior messages.
        """
        response = CLIENT.responses.create(
            conversation=self.conversation.id,
            model=MODEL,
            tools=self.tool_config,
            instructions=self.instructions,
            input=message,
            service_tier=SERVICE_TIER
        )
        print(response.output_text)


# ============================================================================
# SECTION 13: MAIN EXECUTION
# ============================================================================

if __name__ == '__main__':
    """
    This section replicates the notebook cells:
    
    Cell 1: Install package (not needed in standalone script)
    Cell 2: Run the pipeline
    Cell 3: Start chat and ask first question
    Cell 4: Continue chat conversation
    """
    
    print("=" * 70)
    print("EXECUTING DATA PROCESSING PIPELINE")
    print("=" * 70)
    print()
    
    # Equivalent to Cell 2: Run the pipeline
    run()
    
    print()
    print("=" * 70)
    print("STARTING CHAT CONVERSATION")
    print("=" * 70)
    print()
    
    # Equivalent to Cell 3: Start a new conversation
    chat = Chat()
    chat.msg("What would be Jill's percentage of total spend if we did not attribute Amazon purchases to her?")
    
    print()
    
    # Equivalent to Cell 4: Continue the conversation
    chat.msg("What would Jack's be if we attributed them to him?")

