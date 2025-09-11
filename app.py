import streamlit as st
import math
# import base64
from datetime import datetime
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.units import inch
from tinydb import TinyDB, Query
import pandas as pd
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill

# --- DB SETUP (UPDATED) ---
def setup_database():
    """Initializes TinyDB, ensures default products are present, and reads all product names."""
    db = TinyDB('db.json')
    # Setup tables for products and invoices
    product_table = db.table('products')
    db.table('invoices') 
    
    Product = Query()
    default_products = ['sunscreen', 'zebra', 'solid_blackout', 'curtain']
    
    for name in default_products:
        if not product_table.search(Product.name == name):
            product_table.insert({'name': name, 'fields': ['price', 'profit_ratio']})
            
    all_product_names = [p['name'] for p in product_table.all() if 'name' in p and isinstance(p['name'], str)]
    return db, all_product_names

# --- DYNAMICALLY INITIALIZE SESSION STATE ---
def initialize_session_state(products):
    """Initializes session state, dynamically adding keys for all available products."""
    if 'blinds_data' not in st.session_state:
        st.session_state.blinds_data = []
    if 'show_add_form' not in st.session_state:
        st.session_state.show_add_form = False
    if 'prefill_data' not in st.session_state:
        st.session_state.prefill_data = None
    if 'editing_blind_id' not in st.session_state:
        st.session_state.editing_blind_id = None

    if 'universal_profit_margin_enabled' not in st.session_state:
        st.session_state.universal_profit_margin_enabled = False

    if 'motor_price' not in st.session_state:
        st.session_state.motor_price = 0.0
    if 'motor_quantity' not in st.session_state:
        st.session_state.motor_quantity = 0
    if 'motor_shipping_price' not in st.session_state:
        st.session_state.motor_shipping_price = 0.0

    if 'pricing' not in st.session_state:
        st.session_state.pricing = {}
    if 'profit_percentages' not in st.session_state:
        st.session_state.profit_percentages = {}

    defaults = {
        'sunscreen': {'price': 2.1, 'ratio': 0.3, 'profit': 0.7},
        'zebra': {'price': 2.6, 'ratio': 0.3, 'profit': 0.7},
        'solid_blackout': {'price': 1.7, 'ratio': 0.3, 'profit': 0.7},
        'curtain': {'price': 1.9, 'ratio': 0.3, 'profit': 0.7},
    }

    for product in products:
        price_key = f"{product}_price"
        ratio_key = f"{product}_profit_ratio"
        profit_key = f"profit_{product}"
        universal_ratio_key = f"universal_ratio_{product}"

        if price_key not in st.session_state.pricing:
            st.session_state.pricing[price_key] = defaults.get(product, {}).get('price', 1.0)
        if ratio_key not in st.session_state.pricing:
            st.session_state.pricing[ratio_key] = defaults.get(product, {}).get('ratio', 0.3)
        if product not in st.session_state.profit_percentages:
            st.session_state.profit_percentages[product] = defaults.get(product, {}).get('profit', 0.7)
        if universal_ratio_key not in st.session_state:
            st.session_state[universal_ratio_key] = defaults.get(product, {}).get('ratio', 0.3)
        if profit_key not in st.session_state:
            st.session_state[profit_key] = defaults.get(product, {}).get('profit', 0.7)


# --- CALLBACK TO BALANCE PROFIT/RATIO ---
def balance_profits(product_name, changed_field):
    """Callback to ensure profit % and universal ratio for a product sum to 1.0."""
    if not st.session_state.universal_profit_margin_enabled:
        return
    
    try:
        ratio_key = f"universal_ratio_{product_name}"
        profit_key = f"profit_{product_name}"
        
        if changed_field == 'ratio':
            new_ratio = st.session_state.get(ratio_key, 0)
            st.session_state[profit_key] = round(1.0 - new_ratio, 2)
        elif changed_field == 'profit':
            new_profit = st.session_state.get(profit_key, 0)
            st.session_state[ratio_key] = round(1.0 - new_profit, 2)
            
        recalculate_all_blinds() # Recalculate everything after balancing
    except Exception as e:
        st.warning(f"Could not balance profits: {e}")


# --- CALCULATION LOGIC (REVISED) ---
def calculate_blind_costs(width, height, total_blinds, mount, pricing, shipping_rate, selected_products, resize_width):
    """Calculates costs for all selected products using the updated formulas."""
    total_sqft_final = (width * height / 144) * total_blinds
    pieces_to_ship = []
    if resize_width and width > 40:
        remaining_width = width
        while remaining_width > 40:
            pieces_to_ship.append(40.0)
            remaining_width -= 40
        if remaining_width > 0:
            pieces_to_ship.append(float(remaining_width))
    else:
        pieces_to_ship.append(width)

    number_of_splits = len(pieces_to_ship)
    actual_total_pieces = number_of_splits * total_blinds
    shipping_cost_final = 0
    # Ensure shipping rate is not zero to avoid division errors
    if shipping_rate > 0:
        for piece_width in pieces_to_ship:
            width_in_cm_per_piece = (piece_width + 2) * 2.5
            shipping_cost_for_one_piece = (((width_in_cm_per_piece * 13 * 13) / 4850) * 10) / shipping_rate
            shipping_cost_final += shipping_cost_for_one_piece * total_blinds

    product_costs = {}
    for name in selected_products.keys(): 
        is_selected = selected_products.get(name, False)
        cost_key = f"{name}_cost"
        if is_selected:
            price = pricing.get(f'{name}_price', 0)
            ratio = pricing.get(f'{name}_profit_ratio', 1)
            if ratio > 0:
                cost = total_sqft_final * (price / ratio)
            else:
                cost = 0
            product_costs[cost_key] = cost
        else:
            product_costs[cost_key] = 0

    results = {
        'total_sqft': total_sqft_final, 'shipping_cost': shipping_cost_final,
        'actual_total_pieces': actual_total_pieces, 'number_of_splits': number_of_splits,
    }
    results.update(product_costs)
    return results

# --- Recalculation Function for Universal Toggle ---
def recalculate_all_blinds():
    """Loops through all blinds and recalculates their costs based on the current universal profit margin setting."""
    updated_blinds_data = []
    db, available_products = setup_database() 

    for blind in st.session_state.blinds_data:
        recalc_pricing = blind.get('pricing', st.session_state.pricing).copy()
        if st.session_state.get('universal_profit_margin_enabled', False):
            for product_name in available_products:
                ratio_key = f"universal_ratio_{product_name}"
                universal_margin_for_product = st.session_state.get(ratio_key, 0.3)
                recalc_pricing[f"{product_name}_profit_ratio"] = universal_margin_for_product

        updated_costs = calculate_blind_costs(
            width=blind['width'], height=blind['height'], total_blinds=blind['total_blinds'],
            mount=blind['mount'], pricing=recalc_pricing, shipping_rate=blind['shipping_rate'],
            selected_products=blind['selected_products'], resize_width=blind['resize_width']
        )
        updated_blind = blind.copy()
        updated_blind.update(updated_costs)
        updated_blinds_data.append(updated_blind)
    st.session_state.blinds_data = updated_blinds_data


# --- INVOICE GENERATION FUNCTION (Unchanged) ---
def generate_invoice_pdf(invoice_data):
    pass # Placeholder for PDF generation

# --- EXCEL GENERATION FUNCTION (UPDATED) ---
# --- EXCEL GENERATION FUNCTION (UPDATED) ---
def generate_excel_report(blinds_data, session_state, active_products):
    """
    Generates an Excel report with a comprehensive layout.
    - Adds Total, Split, and Mount columns.
    - Updates formulas to use the 'Total' column as the quantity.
    - Re-adds the Motor as the last row in the main table.
    - Provides a detailed summary table below the main table.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Blinds Calculation"

    # --- STYLES ---
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    input_fill = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
    summary_label_font = Font(bold=True)
    bill_total_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")

    # --- DATA TABLE SECTION ---
    table_start_row = 1
    
    # Define headers with new columns (Resize removed)
    headers = ['ID', 'Desc', 'W', 'H', 'Undivided', 'Total', 'Split', 'Mount', 'Total Sq Ft']
    for product in active_products:
        headers.append(f"{product.replace('_', ' ').capitalize()} Cost")
    headers.extend(['Shipping Cost', 'Line Total'])
    
    for i, header in enumerate(headers, 1):
        cell = ws.cell(row=table_start_row, column=i, value=header)
        cell.font = header_font
        cell.fill = header_fill

    # --- WRITE BLIND DATA ROWS ---
    row_num = table_start_row + 1
    for blind in sorted(blinds_data, key=lambda x: x['id']):
        # Write input and descriptive values
        ws.cell(row=row_num, column=1, value=blind['id'])
        ws.cell(row=row_num, column=2, value=blind.get('description', 'N/A'))
        ws.cell(row=row_num, column=3, value=blind['width']).fill = input_fill
        ws.cell(row=row_num, column=4, value=blind['height']).fill = input_fill
        ws.cell(row=row_num, column=5, value=blind['total_blinds']) # Undivided
        ws.cell(row=row_num, column=6, value=blind.get('actual_total_pieces', blind['total_blinds'])) # Total
        
        number_of_splits = blind.get('number_of_splits', 1)
        split_display = f"{blind['width']} / {number_of_splits}" if number_of_splits > 1 else "-"
        ws.cell(row=row_num, column=7, value=split_display) # Split
        ws.cell(row=row_num, column=8, value=blind['mount']) # Mount

        # Define cell references for formulas
        w_cell, h_cell, num_cell_undivided, num_cell_total = f'C{row_num}', f'D{row_num}', f'E{row_num}', f'F{row_num}'
        
        # Formula for Total Sq Ft (Col I) - uses undivided blinds for area calculation
        sqft_formula = f"=IFERROR((({w_cell}*{h_cell})/144)*{num_cell_undivided}, 0)"
        ws.cell(row=row_num, column=9, value=sqft_formula)
        sqft_cell = f'I{row_num}'
        
        # Formulas for each product cost
        product_cost_cells = []
        col_idx = 10 # Start of product cost columns
        for p in active_products:
            blind_pricing = blind.get('pricing', {})
            price = blind_pricing.get(f'{p}_price', session_state.pricing.get(f'{p}_price', 0))
            ratio = blind_pricing.get(f'{p}_profit_ratio', session_state.pricing.get(f'{p}_profit_ratio', 1))
            
            p_formula = f"=IFERROR(IF({ratio}>0, {sqft_cell}*({price}/{ratio}), 0), 0)"
            
            if not blind.get('selected_products', {}).get(p, False): p_formula = 0
            
            ws.cell(row=row_num, column=col_idx, value=p_formula)
            product_cost_cells.append(f'{get_column_letter(col_idx)}{row_num}')
            col_idx += 1

        # Formula for Shipping Cost - uses total pieces (with splits) for quantity
        shipping_rate = blind.get('shipping_rate', 0.9)
        shipping_formula = f"=IF({shipping_rate}>0, (((((({w_cell}+2)*2.5)*13*13)/4850)*10)/{shipping_rate})*{num_cell_total}, 0)"
        ws.cell(row=row_num, column=col_idx, value=shipping_formula)
        shipping_cell = f'{get_column_letter(col_idx)}{row_num}'; col_idx += 1
        
        # Formula for Line Total
        line_total_formula = f"=SUM({','.join(product_cost_cells)}, {shipping_cell})"
        ws.cell(row=row_num, column=col_idx, value=line_total_formula)
        
        row_num += 1

    # --- ADD MOTOR ROW AS LAST ITEM IN TABLE ---
    if session_state.motor_quantity > 0:
        ws.cell(row=row_num, column=2, value="Motor") # Description
        ws.cell(row=row_num, column=5, value=session_state.motor_quantity) # Undivided
        ws.cell(row=row_num, column=6, value=session_state.motor_quantity) # Total
        
        first_product_col_idx = 10
        shipping_col_idx = 9 + len(active_products) + 1
        total_col_idx = shipping_col_idx + 1

        ws.cell(row=row_num, column=first_product_col_idx, value=session_state.motor_price) # Price in first product col
        ws.cell(row=row_num, column=shipping_col_idx, value=session_state.motor_shipping_price) # Shipping Cost

        # Formula for Motor Line Total
        motor_qty_cell = f'F{row_num}'
        motor_price_cell = f'{get_column_letter(first_product_col_idx)}{row_num}'
        motor_shipping_cell = f'{get_column_letter(shipping_col_idx)}{row_num}'
        # motor_total_formula = f"=({motor_qty_cell}*{motor_price_cell})+{motor_shipping_cell}"
        motor_total_formula = f"=(({motor_price_cell} + {motor_shipping_cell})*{motor_qty_cell})"
        ws.cell(row=row_num, column=total_col_idx, value=motor_total_formula)
        
        row_num += 1

    # --- NEW SUMMARY TABLE ---
    last_data_row = row_num - 1
    last_blind_row = last_data_row - (1 if session_state.motor_quantity > 0 else 0)
    summary_start_row = row_num + 1
    
    label_col = 2
    value_col = 3
    current_summary_row = summary_start_row

    # 1. Total Estimated Shipping
    shipping_col_letter = get_column_letter(9 + len(active_products) + 1)
    shipping_total_formula = f"=SUM({shipping_col_letter}{table_start_row+1}:{shipping_col_letter}{last_data_row})"
    ws.cell(row=current_summary_row, column=label_col, value="Total Estimated Shipping:")
    ws.cell(row=current_summary_row, column=value_col, value=shipping_total_formula).number_format = '"$"#,##0.00'
    current_summary_row += 1

    # 2. Product Only Costs (summing only blind rows)
    for i, p in enumerate(active_products):
        product_col_letter = get_column_letter(10 + i)
        product_total_formula = f"=SUM({product_col_letter}{table_start_row+1}:{product_col_letter}{last_blind_row})"
        
        p_clean = p.replace('_', ' ').capitalize()
        ws.cell(row=current_summary_row, column=label_col, value=f"{p_clean} Only Cost")
        product_total_cell = ws.cell(row=current_summary_row, column=value_col, value=product_total_formula)
        product_total_cell.number_format = '"$"#,##0.00'
        current_summary_row += 1

    # 3. Bill Total
    total_col_letter = get_column_letter(len(headers))
    bill_total_formula = f"=SUM({total_col_letter}{table_start_row+1}:{total_col_letter}{last_data_row})"
    
    bill_total_label_cell = ws.cell(row=current_summary_row, column=label_col, value="Bill Total:")
    bill_total_label_cell.font = summary_label_font
    bill_total_label_cell.fill = bill_total_fill
    
    bill_total_value_cell = ws.cell(row=current_summary_row, column=value_col, value=bill_total_formula)
    bill_total_value_cell.font = summary_label_font
    bill_total_value_cell.fill = bill_total_fill
    bill_total_value_cell.number_format = '"$"#,##0.00'
    
    # --- FINAL STYLING & Column Widths ---
    for col_idx_num in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col_idx_num)].width = 15
    ws.column_dimensions['B'].width = 30

    # --- SAVE TO MEMORY BUFFER ---
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

# --- ADD/EDIT FORM (Unchanged) ---
def add_blind_form(available_products):
    is_editing = st.session_state.editing_blind_id is not None
    
    if is_editing and st.session_state.prefill_data:
        defaults = st.session_state.prefill_data
    else:
        defaults = {
            'description': "", 'width': 36.0, 'height': 95.5, 'total_blinds': 2, 'mount': "Inside Mt",
            'shipping_rate': 0.9, 'resize_width': True, 'selected_products': {}, 'pricing': st.session_state.pricing
        }

    if 'form_product_selection' not in st.session_state:
        st.session_state.form_product_selection = [name for name, selected in defaults.get('selected_products', {}).items() if selected]

    form_title = "✏️ Edit Blind" if is_editing else "➕ Add New Blind"
    st.subheader(form_title)
    
    st.multiselect("Products", options=available_products, default=st.session_state.form_product_selection, key="form_product_selection")

    with st.form("add_edit_blind_form"):
        description = st.text_input("Description", value=defaults.get('description', ''), placeholder="e.g., Living room window")
        col1, col2 = st.columns(2)
        with col1:
            width = st.number_input("Width (inches)", min_value=1.0, value=float(defaults.get('width')), step=0.5)
            height = st.number_input("Height (inches)", min_value=1.0, value=float(defaults.get('height')), step=0.5)
        with col2:
            total_blinds = st.number_input("Number of Blinds", min_value=1, value=int(defaults.get('total_blinds')))
            mount = st.selectbox("Mount Type", ["Inside Mt", "Outside Mt"], index=["Inside Mt", "Outside Mt"].index(defaults.get('mount', "Inside Mt")))
        
        resize_width = st.checkbox("Resize Width", value=defaults.get('resize_width', True))
        shipping_rate = st.number_input("Shipping Rate", min_value=0.1, value=float(defaults.get('shipping_rate')), step=0.1)
        
        selected_product_names = st.session_state.form_product_selection
        pricing_inputs = {}
        if selected_product_names:
            st.markdown("**Price Settings**")
            price_cols = st.columns(len(selected_product_names))
            use_universal_margin = st.session_state.universal_profit_margin_enabled

            for i, name in enumerate(selected_product_names):
                with price_cols[i]:
                    st.markdown(f"*{name.replace('_', ' ').capitalize()}*")
                    price_key, ratio_key = f"{name}_price", f"{name}_profit_ratio"
                    default_price = defaults.get('pricing', {}).get(price_key, st.session_state.pricing.get(price_key, 0))
                    if use_universal_margin:
                        default_ratio = st.session_state.get(f"universal_ratio_{name}", 0.3)
                    else:
                        default_ratio = defaults.get('pricing', {}).get(ratio_key, st.session_state.pricing.get(ratio_key, 0))
                    price_str = st.text_input("Price", value=str(default_price), key=f"price_{name}")
                    ratio_str = st.text_input("Profit Ratio", value=str(default_ratio), key=f"ratio_{name}", disabled=use_universal_margin)
                    pricing_inputs[name] = {'price_str': price_str, 'ratio_str': ratio_str}

        submit_col, cancel_col = st.columns(2)
        with submit_col:
            submitted = st.form_submit_button("✅ " + ("Update Blind" if is_editing else "Add Blind to Table"), type="primary")
        with cancel_col:
            if st.form_submit_button("❌ Cancel"):
                st.session_state.show_add_form = False
                st.session_state.prefill_data, st.session_state.editing_blind_id = None, None
                del st.session_state.form_product_selection
                st.rerun()

        if submitted:
            custom_pricing = {}
            try:
                for name, inputs in pricing_inputs.items():
                    custom_pricing[f"{name}_price"] = float(inputs['price_str'])
                    custom_pricing[f"{name}_profit_ratio"] = float(inputs['ratio_str'])
            except ValueError:
                st.error("Text not allowed. Please enter valid numbers for prices and profit ratios.")
                st.stop()

            selected_products = {name: (name in selected_product_names) for name in available_products}
            final_pricing = st.session_state.pricing.copy()
            final_pricing.update(custom_pricing)
            
            if st.session_state.universal_profit_margin_enabled:
                for product_name in available_products:
                    ratio_key = f"universal_ratio_{product_name}"
                    universal_margin = st.session_state.get(ratio_key, 0.3)
                    final_pricing[f"{product_name}_profit_ratio"] = universal_margin

            costs = calculate_blind_costs(width, height, total_blinds, mount, final_pricing, shipping_rate, selected_products, resize_width)
            blind_id = st.session_state.editing_blind_id or ((max(b['id'] for b in st.session_state.blinds_data) + 1) if st.session_state.blinds_data else 1)
            
            if is_editing:
                st.session_state.blinds_data = [b for b in st.session_state.blinds_data if b['id'] != blind_id]

            new_blind_data = {
                'id': blind_id, 'description': description, 'width': width, 'height': height,
                'total_blinds': total_blinds, 'mount': mount, 'shipping_rate': shipping_rate,
                'resize_width': resize_width, 'selected_products': selected_products, 
                'pricing': final_pricing, **costs
            }
            st.session_state.blinds_data.append(new_blind_data)

            st.success(f"Blind #{blind_id} processed successfully!")
            st.session_state.show_add_form = False
            st.session_state.prefill_data, st.session_state.editing_blind_id = None, None
            del st.session_state.form_product_selection
            st.rerun()

# --- DISPLAY TABLE (Unchanged) ---
def display_blinds_table():
    if not st.session_state.blinds_data:
        return

    st.subheader("📋 Blinds Summary")
    
    active_products = sorted(list(set(
        key.replace('_cost', '') 
        for blind in st.session_state.blinds_data 
        for key in blind 
        if key.endswith('_cost') and blind[key] > 0 and key != 'shipping_cost'
    )))
    
    headers = ['ID', 'Desc', 'W', 'H', 'Undivided', 'Total', 'Split', 'Resize', 'Mount', 'Sq Ft']
    headers.extend([p.replace('_', ' ').capitalize() for p in active_products])
    headers.extend(['Shipping', 'Edit', 'Delete'])
    
    header_cols = st.columns(len(headers))
    for i, header in enumerate(headers):
        header_cols[i].markdown(f"**{header}**")
    st.markdown("---")

    for blind in sorted(st.session_state.blinds_data, key=lambda x: x['id']):
        cols = st.columns(len(headers))
        number_of_splits = blind.get('number_of_splits', 1)
        split_display = f"{blind['width']} / {number_of_splits}" if number_of_splits > 1 else "-"
        row_data_static = [
            blind['id'], blind.get('description', 'N/A'), f"{blind['width']}\"", f"{blind['height']}\"",
            blind['total_blinds'], blind.get('actual_total_pieces', blind['total_blinds']),
            split_display, "Yes" if blind.get('resize_width') else "No", blind['mount'], f"{blind['total_sqft']:.2f}"
        ]
        for j, value in enumerate(row_data_static):
            cols[j].write(value)
            
        col_offset = len(row_data_static)
        for i, product_name in enumerate(active_products):
            cost = blind.get(f'{product_name}_cost', 0)
            cols[col_offset + i].write(f"${cost:.2f}" if cost > 0 else "-")
            
        cols[-3].write(f"${blind.get('shipping_cost', 0):.2f}")
        with cols[-2]:
            if st.button("✏️", key=f"edit_{blind['id']}", help=f"Edit Blind {blind['id']}"):
                st.session_state.prefill_data, st.session_state.editing_blind_id = blind, blind['id']
                st.session_state.show_add_form = True
                st.rerun()
        with cols[-1]:
            if st.button("🗑️", key=f"delete_{blind['id']}", help=f"Delete Blind {blind['id']}"):
                st.session_state.blinds_data = [b for b in st.session_state.blinds_data if b['id'] != blind['id']]
                st.success(f"Blind #{blind['id']} deleted!")
                recalculate_all_blinds()
                st.rerun()

# --- MAIN APPLICATION FLOW (UPDATED)---
def main():
    st.set_page_config(page_title="Blinds Cost Calculator", layout="wide")
    st.title("🪟 Blinds Cost Calculator")
    
    db, available_products = setup_database()
    initialize_session_state(available_products)

    # --- UPDATED: LOAD & DELETE INVOICE UI ---
    st.sidebar.title("Invoice History")
    invoices_table = db.table('invoices')
    saved_invoices = invoices_table.all()
    invoice_names = ["--- Start New Invoice ---"] + sorted([inv.get('name', f"Untitled_{inv.doc_id}") for inv in saved_invoices], reverse=True)
    
    selected_invoice_name = st.sidebar.selectbox("Load Saved Invoice", invoice_names, key="invoice_selector")
    
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("Load Invoice"):
            if selected_invoice_name != "--- Start New Invoice ---":
                Invoice = Query()
                invoice_data = invoices_table.get(Invoice.name == selected_invoice_name)
                if invoice_data:
                    # Overwrite session state with loaded data
                    for key, value in invoice_data.get('session_data', {}).items():
                        st.session_state[key] = value
                    
                    st.success(f"Invoice '{selected_invoice_name}' loaded successfully!")
                    st.rerun()
            else:
                st.sidebar.info("Select an invoice to load.")
    with col2:
        if st.button("Delete Invoice", help="Deletes the selected invoice permanently."):
            if selected_invoice_name != "--- Start New Invoice ---":
                Invoice = Query()
                invoices_table.remove(Invoice.name == selected_invoice_name)
                st.sidebar.success(f"Deleted '{selected_invoice_name}'.")
                # Reset the selector to avoid errors
                st.session_state.invoice_selector = "--- Start New Invoice ---"
                st.rerun()
            else:
                st.sidebar.warning("Select an invoice to delete.")


    st.markdown("---")
    if st.session_state.show_add_form: 
        add_blind_form(available_products)
    else:
        if st.button("➕ Add New Blind", type="primary"):
            st.session_state.show_add_form = True
            st.session_state.prefill_data, st.session_state.editing_blind_id = None, None
            if 'form_product_selection' in st.session_state:
                del st.session_state.form_product_selection
            st.rerun()
    st.markdown("---")
    
    display_blinds_table()
    
    if st.session_state.blinds_data:
        st.markdown("---")
        active_products_for_settings = sorted(list(set(
            p for blind in st.session_state.blinds_data
            for p, selected in blind.get('selected_products', {}).items() if selected
        )))
        
        st.subheader("⚙️ Universal Profit Ratio")
        st.checkbox("Apply Universal Profit Margin", key="universal_profit_margin_enabled", on_change=recalculate_all_blinds,
            help="Check this to use a specific profit ratio for each active product. Uncheck to revert to individual settings per blind.")
        
        if st.session_state.universal_profit_margin_enabled:
            if not active_products_for_settings:
                st.info("Add a blind and select products to set their universal profit ratios.")
            else:
                ratio_cols = st.columns(len(active_products_for_settings))
                for i, p_name in enumerate(active_products_for_settings):
                    with ratio_cols[i]:
                        st.number_input(f"{p_name.replace('_',' ').capitalize()} Ratio", min_value=0.01, max_value=1.0,
                            step=0.01, format="%.2f", key=f"universal_ratio_{p_name}", 
                            on_change=balance_profits, args=(p_name, 'ratio'))
        st.markdown("---")

        st.subheader("Profit Settings")
        if not active_products_for_settings:
            st.info("Add a blind and select products to set their final profit percentages.")
        else:
            profit_cols = st.columns(len(active_products_for_settings))
            for i, p_name in enumerate(active_products_for_settings):
                with profit_cols[i]:
                    st.number_input(f"{p_name.replace('_',' ').capitalize()} Profit %", min_value=0.0, max_value=1.0, 
                        step=0.01, format="%.2f", key=f"profit_{p_name}",
                        on_change=balance_profits, args=(p_name, 'profit'),
                        disabled=st.session_state.universal_profit_margin_enabled)
        st.markdown("---")

        st.subheader("⚙️ Motor Settings")
        motor_cols = st.columns(3)
        with motor_cols[0]:
            st.number_input("Motor Price ($)", min_value=0.0, key="motor_price", step=10.0, format="%.2f")
        with motor_cols[1]:
            st.number_input("Motor Quantity", min_value=0, key="motor_quantity", step=1)
        with motor_cols[2]:
            st.number_input("Motor Shipping ($)", min_value=0.0, key="motor_shipping_price", step=5.0, format="%.2f")
        st.markdown("---")

        st.subheader("💰 Cost Summary")

        sub_totals = {p: sum(b.get(f'{p}_cost', 0) for b in st.session_state.blinds_data) for p in available_products}
        shipping_totals = {p: sum(b.get('shipping_cost', 0) for b in st.session_state.blinds_data if b.get('selected_products', {}).get(p)) for p in available_products}
        
        profit_totals = {p: ((sub_totals[p] + shipping_totals[p]) * st.session_state.get(f"profit_{p}", 0)) for p in available_products}

        total_motor_cost = st.session_state.motor_quantity * (st.session_state.motor_price + st.session_state.motor_shipping_price)
        
        net_profit = sum(profit_totals.values())
        total_sqft = sum(b.get('total_sqft', 0) for b in st.session_state.blinds_data) 
        total_pieces = sum(b.get('actual_total_pieces', b.get('total_blinds', 0)) for b in st.session_state.blinds_data)
        overall_sub_total = sum(sub_totals.values())
        overall_shipping_total = sum(b.get('shipping_cost', 0) for b in st.session_state.blinds_data)
        bill_total = overall_sub_total + overall_shipping_total + total_motor_cost

        active_products_summary = {p: v for p, v in sub_totals.items() if v > 0}
        num_summary_cols = len(active_products_summary) + 1 if active_products_summary else 1
        summary_cols = st.columns(num_summary_cols)

        i = 0
        for p_name, sub_total_val in active_products_summary.items():
            with summary_cols[i]:
                st.metric(f"{p_name.replace('_',' ').capitalize()} Sub-Total", f"${sub_total_val:.2f}")
                st.metric(f"{p_name.replace('_',' ').capitalize()} Est. Shipping", f"${shipping_totals[p_name]:.2f}")
                st.metric(f"{p_name.replace('_',' ').capitalize()} Profit", f"${profit_totals[p_name]:.2f}")
            i += 1
        
        with summary_cols[-1]:
            st.metric("Total Sq Ft", f"{total_sqft:.2f}")
            st.metric("Total Pieces", f"{total_pieces}")
            st.metric("Motor Cost", f"${total_motor_cost:.2f}")
            st.metric("💵 Bill Total", f"${bill_total:.2f}")
            st.metric("🎯 Net Profit", f"${net_profit:.2f}")
        st.markdown("---")
        
        # --- UPDATED: SAVE & DOWNLOAD SECTION ---
        st.subheader("Actions")
        col1, col2 = st.columns(2)
        with col1:
            st.info("Download a report of the current invoice.")
            dl_col1, dl_col2 = st.columns(2)
            with dl_col1:
                st.button("📄 Download Invoice (PDF)")
            with dl_col2:
                excel_data = generate_excel_report(
                    st.session_state.blinds_data,
                    st.session_state,
                    active_products_for_settings
                )
                st.download_button(
                    label="📄 Download Excel Report",
                    data=excel_data,
                    file_name=f"blinds_report_formulas_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )

        with col2:
            st.info("Save the current invoice to the database.")
            invoice_name = st.text_input("Invoice Name", placeholder="e.g., Smith Job - Phase 1")
            if st.button("💾 Save Current Invoice", type="primary"):
                if invoice_name:
                    # **FIXED**: Selectively save only necessary data, not widget states
                    keys_to_save = [
                        'blinds_data', 'motor_price', 'motor_quantity', 
                        'motor_shipping_price', 'universal_profit_margin_enabled', 'pricing'
                    ]
                    session_data_to_save = {key: st.session_state[key] for key in keys_to_save if key in st.session_state}
                    
                    # Add dynamic keys like profit and ratio settings
                    for key in st.session_state:
                        if key.startswith('profit_') or key.startswith('universal_ratio_'):
                            session_data_to_save[key] = st.session_state[key]

                    invoice_data = {
                        "name": invoice_name,
                        "saved_at": datetime.now().isoformat(),
                        "session_data": session_data_to_save
                    }
                    
                    Invoice = Query()
                    invoices_table.upsert(invoice_data, Invoice.name == invoice_name)
                    st.success(f"Invoice '{invoice_name}' saved successfully!")
                    st.rerun() # Rerun to update the sidebar list
                else:
                    st.warning("Please enter an invoice name before saving.")
        
        st.markdown("---")
        if st.button("🗑️ Clear All Blinds"):
            st.session_state.blinds_data = []
            st.session_state.motor_quantity = 0
            st.rerun()

    st.markdown("---")
    with st.expander("📐 View Calculation Formulas"):
        st.markdown("""
        **1. Core Blind Calculation (per line item):**
        - **Total Sq Ft** = `((Width * Height) / 144) * Number of Blinds`
        - **Product Sub-Total** = `Total Sq Ft * (Product Price / Profit Ratio)`
        
        **2. Shipping Cost Calculation:**
        - `Shipping Cost (per piece)` = `(((Width in CM * 13 * 13) / 4850) * 10) / Shipping Rate`
        - `Total Shipping Cost` = Sum of `Shipping Cost (per piece)` for all physical pieces.

        **3. Final Cost Summary Calculations:**
        - `Product Profit` = `(Product Sub-Total + Product Est. Shipping) * Product Profit %`
        - **Balancing**: If Universal Profit is enabled, `Profit Ratio + Profit % = 1.0`
        - `Net Profit` = Sum of all `Product Profit` values.
        - `Bill Total` = `Overall Sub-Total` + `Total Estimated Shipping` + `Total Motor Cost`
        """)

if __name__ == "__main__":
    main()