import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import time

# --- CONFIGURACIÓN ---
ARCHIVO_ENTRADA = "MX GBS  to do.xlsx"
ARCHIVO_SALIDA = "MX GBS  to do_PROCESADO.xlsx"
HOJA = "2025 wages"
MAX_INTENTOS = 3  # Número de vidas por empleado

def esperar_y_click(driver, by, selector, nombre_elemento="elemento"):
    try:
        # Esperamos a que sea visible y clickable
        elemento = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((by, selector))
        )
        # Forzamos el click con JavaScript si el click normal falla
        try:
            elemento.click()
        except:
            driver.execute_script("arguments[0].click();", elemento)
            
        print(f"   > Click en: {nombre_elemento}")
        time.sleep(1) # PAUSA ZEN
        return True
    except Exception as e:
        print(f"   X Error buscando {nombre_elemento}: {e}")
        return False

def esperar_y_escribir(driver, by, selector, texto, nombre_elemento="campo"):
    try:
        # Usamos element_to_be_clickable para asegurar que no esté deshabilitado
        elemento = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((by, selector))
        )
        elemento.click() # Damos foco primero
        time.sleep(0.5)  # Pequeña espera tras el foco
        elemento.clear()
        elemento.send_keys(texto)
        print(f"   > Escribiendo en {nombre_elemento}")
        time.sleep(1) # PAUSA ZEN
        return True
    except Exception as e:
        print(f"   X Error escribiendo en {nombre_elemento}: {e}")
        return False

def procesar_adp():
    print("Leyendo Excel...")
    try:
        df = pd.read_excel(ARCHIVO_ENTRADA, sheet_name=HOJA, dtype=str)
        df.columns = df.columns.str.strip()
    except Exception as e:
        print(f"Error leyendo archivo: {e}")
        return

    # --- IDENTIFICAR COLUMNA DE SALIDA ---
    col_p = 'If YES change it to P'
    cols_match = [c for c in df.columns if 'If YES change it to P' in c]
    target_col = cols_match[0] if cols_match else col_p
    print(f"ℹ️  Los resultados (p/E) se guardarán en la columna: '{target_col}'")

    # --- VALIDACIÓN DE COLUMNAS DE LECTURA ---
    col_wages = 'Wages-2025'
    if col_wages not in df.columns:
        cols_posibles = [c for c in df.columns if 'Wages' in c]
        if cols_posibles:
            col_wages = cols_posibles[0]
            print(f"⚠️ Usando columna de lectura: '{col_wages}'")
        else:
            print("❌ Error: No encuentro la columna 'Wages-2025'.")
            return

    # --- FILTRADO ---
    try:
        col_grupo = 'Pay Group'
        col_id = 'EEID'
        
        # --- NUEVA LÓGICA: SELECCIÓN DE PAY GROUPS ---
        # 1. Obtener la lista única de grupos del Excel
        grupos_disponibles = sorted(df[col_grupo].dropna().astype(str).str.strip().unique().tolist())
        
        print("\n" + "="*50)
        print("GRUPOS DE PAGO (PAY GROUPS) ENCONTRADOS:")
        for idx, grupo in enumerate(grupos_disponibles, 1):
            print(f"  {idx}. {grupo}")
        print("="*50)

        # 2. Pedir al usuario que seleccione
        while True:
            seleccion = input("\n👉 Ingresa los NÚMEROS de los grupos a procesar (separados por coma, ej: 1,3)\no presiona ENTER para procesar TODOS: ").strip()
            
            grupos_elegidos = []
            
            if not seleccion:
                grupos_elegidos = grupos_disponibles
                print(f"✅ Seleccionados TODOS los grupos.")
                break
            else:
                try:
                    # Convertir input "1, 3" -> índices y obtener nombres
                    numeros = [int(n.strip()) for n in seleccion.split(',') if n.strip()]
                    for n in numeros:
                        if 1 <= n <= len(grupos_disponibles):
                            grupos_elegidos.append(grupos_disponibles[n-1])
                        else:
                            print(f"⚠️ El número {n} no es válido y será ignorado.")
                    
                    if grupos_elegidos:
                        print(f"✅ Grupos seleccionados: {grupos_elegidos}")
                        break
                    else:
                        print("❌ No seleccionaste ningún grupo válido. Intenta de nuevo.")
                except ValueError:
                    print("❌ Entrada no válida (solo números y comas). Intenta de nuevo.")

        # 3. Aplicar el filtro con la selección del usuario
        filtro_grupo = df[col_grupo].str.strip().isin(grupos_elegidos)
        filtro_wages = df[col_wages].str.strip().str.lower() == 'yes'
        filtro_flag = df[target_col].astype(str).str.strip().str.upper() == 'D'

        # --- SELECCIONAR TODOS LOS EMPLEADOS FILTRADOS ---
        indices_a_procesar = df[filtro_grupo & filtro_wages & filtro_flag].index.tolist()
        total_items = len(indices_a_procesar)
        
        print(f"--- LISTO PARA PROCESAR: {total_items} EMPLEADOS ---")
    except Exception as e:
        print(f"Error en filtros: {e}")
        return

    # 2. INICIAR NAVEGADOR
    driver = webdriver.Chrome()
    driver.maximize_window()
    driver.get("https://my.adp.com/?REASON=ERROR_TIMEOUT#/People_ttd_pracTaxWithholding/pracTaxWithholding")

    input("\n⚠️  INICIA SESIÓN MANUALMENTE.\nPresiona ENTER aquí cuando veas la barra de búsqueda...")

    fecha_hoy = datetime.now().strftime("%m/%d/%Y")
    tiempo_inicio = time.time() # Marca de tiempo inicial para cálculos de ETA

    # 3. BUCLE PRINCIPAL
    for i, indice in enumerate(indices_a_procesar): 
        
        procesados = i + 1
        faltantes = total_items - procesados
        
        # --- CÁLCULO DE TIEMPO ESTIMADO (ETA) ---
        tiempo_actual = time.time()
        tiempo_transcurrido = tiempo_actual - tiempo_inicio
        tiempo_promedio = tiempo_transcurrido / procesados
        tiempo_restante_seg = tiempo_promedio * faltantes
        mins_restantes, segs_restantes = divmod(tiempo_restante_seg, 60)
        
        eta_str = f"{int(mins_restantes)}m {int(segs_restantes)}s"

        row = df.loc[indice]
        empleado_id = row[col_id] # Usamos la columna EEID como dato base
        
        if pd.isna(empleado_id):
            continue

        print(f"\n==================================================")
        print(f"PROGRESO: {procesados} de {total_items} | FALTAN: {faltantes}")
        print(f"TIEMPO RESTANTE ESTIMADO: {eta_str}")
        print(f"Procesando ID: {empleado_id} (Fila Excel: {indice + 2})")
        print(f"==================================================")

        exito_este_empleado = False

        # --- SISTEMA DE 3 VIDAS (RETRIES) ---
        for intento in range(1, MAX_INTENTOS + 1):
            if intento > 1:
                print(f"   🔄 INTENTO DE RECUPERACIÓN #{intento}...")
            
            try:
                encontrado = False
                
                # A. BÚSQUEDA PRIORIDAD 1: FILE NUMBER (Antes era la segunda opción)
                try:
                    caja_file = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "gridSearchFileNumber")))
                    caja_file.clear()
                    caja_file.send_keys(empleado_id)
                    caja_file.send_keys(Keys.RETURN)
                    time.sleep(2)

                    lista_resultados = driver.find_elements(By.ID, "peopleSearchGrid_row_0_cell_1_hyperlink")
                    if len(lista_resultados) > 0:
                        print("   > Encontrado por File Number")
                        lista_resultados[0].click()
                        encontrado = True
                except:
                    pass # Si falla, pasamos a la siguiente estrategia

                # B. BÚSQUEDA PRIORIDAD 2: EMPLOYEE ID (Si no encontró por File Number)
                if not encontrado:
                    print("   > No encontrado por File Number. Intentando Employee ID...")
                    try:
                        # Limpiamos búsqueda anterior si es necesario o buscamos el campo ID
                        try: driver.find_element(By.XPATH, "//span[contains(text(), 'NEW SEARCH')]").click()
                        except: pass
                        time.sleep(1)

                        caja_id = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "gridSearchEmployeeId")))
                        caja_id.clear()
                        caja_id.send_keys(empleado_id)
                        caja_id.send_keys(Keys.RETURN)
                        time.sleep(2) 

                        lista_resultados = driver.find_elements(By.ID, "peopleSearchGrid_row_0_cell_1_hyperlink")

                        if len(lista_resultados) > 0:
                            print("   > Encontrado por Employee ID")
                            lista_resultados[0].click()
                            encontrado = True
                        else:
                            print("   ❌ NO ENCONTRADO EN EL SISTEMA (Ni por File ni por ID).")
                            try: driver.find_element(By.XPATH, "//span[contains(text(), 'NEW SEARCH')]").click()
                            except: pass
                            break # Rompemos el ciclo de intentos
                    except:
                        pass

                if encontrado:
                    time.sleep(4) 

                    # 1. Click Make Changes
                    esperar_y_click(driver, By.ID, "displayMakeChangesButton", "Botón Make Changes")
                    
                    # 2. Escribir Fecha
                    esperar_y_escribir(driver, By.ID, "payPeriodDate", fecha_hoy, "Campo Fecha")

                    # 3. Click Done
                    esperar_y_click(driver, By.ID, "makeChangesButton", "Botón Done")
                    time.sleep(2) 

                    # 4. Tab Additional Federal
                    esperar_y_click(driver, By.XPATH, "//span[contains(text(), 'Additional Federal')]", "Tab Additional Federal")
                    time.sleep(2) 

                    # 5. NUEVA LÓGICA DE SELECCIÓN (CLICK FLECHA + CLICK OPCIÓN)
                    print("   > Buscando menú desplegable 'Qualified Pension'...")
                    
                    # Paso A: Click en la flecha
                    xpath_flecha = "//div[@widgetid='addFederalQualifiedPension']//input[contains(@class, 'dijitArrowButtonInner')]"
                    if not esperar_y_click(driver, By.XPATH, xpath_flecha, "Flecha Dropdown"):
                        # Si falla, intentar click en el input mismo para desplegar
                        print("   > Intentando click directo en el campo (Fallback)...")
                        xpath_input = "//div[@widgetid='addFederalQualifiedPension']//input[contains(@class, 'dijitInputInner')]"
                        esperar_y_click(driver, By.XPATH, xpath_input, "Input Qualified Pension")

                    time.sleep(1.5) # Importante: esperar a que la lista se renderice en pantalla

                    # Paso B: Buscar y clickear la opción por su texto visible
                    # ADP suele poner las opciones en un contenedor 'dijitPopup' o tabla flotante al final del DOM.
                    # Usamos un XPath que busque CUALQUIER elemento que contenga el texto "P - Print X"
                    print("   > Buscando opción 'P - Print X' en la lista desplegada...")
                    xpath_opcion = "//*[contains(text(), 'P - Print X')]"
                    
                    exito_opcion = esperar_y_click(driver, By.XPATH, xpath_opcion, "Opción 'P - Print X'")
                    
                    if not exito_opcion:
                        print("   ⚠️ No encontré la opción en el menú. Verifique si el texto es exacto.")
                        # Opcional: imprimir qué opciones ve si falla (para depuración futura)

                    # 6. Guardar
                    if esperar_y_click(driver, By.ID, "saveButton", "Botón Save"):
                        print("   ✅ ¡GUARDADO EXITOSO!")
                        
                        # --- ÉXITO: GUARDAR 'p' ---
                        try:
                            df.at[indice, target_col] = 'p'
                            df.to_excel(ARCHIVO_SALIDA, sheet_name=HOJA, index=False)
                            print(f"   💾 Excel actualizado ('p')")
                        except Exception as e:
                            print(f"   ⚠️  Error guardando Excel: {e}")

                        time.sleep(4) 
                        exito_este_empleado = True

                    # 7. New Search
                    exito_search = esperar_y_click(driver, By.XPATH, "//span[contains(text(), 'NEW SEARCH')]", "Botón New Search")
                    if not exito_search:
                         driver.get("https://my.adp.com/?REASON=ERROR_TIMEOUT#/People_ttd_pracTaxWithholding/pracTaxWithholding")
                    
                    time.sleep(3) 
                    
                    if exito_este_empleado:
                        break # Salir del bucle de intentos

            except Exception as e:
                print(f"   ⚠️  ERROR EN INTENTO {intento}: {e}")
                driver.get("https://my.adp.com/?REASON=ERROR_TIMEOUT#/People_ttd_pracTaxWithholding/pracTaxWithholding")
                time.sleep(5)
        
        # --- FALLO TOTAL: GUARDAR 'E' ---
        if not exito_este_empleado:
            print(f"   ❌❌ FALLÓ EL EMPLEADO {empleado_id}. MARCANDO 'E' EN EXCEL.")
            try:
                df.at[indice, target_col] = 'E'
                df.to_excel(ARCHIVO_SALIDA, sheet_name=HOJA, index=False)
                print(f"   💾 Excel actualizado ('E')")
            except Exception as e:
                print(f"   ⚠️  Error guardando Excel de error: {e}")

    print("\n" + "="*50)
    print("¡PROCESO COMPLETADO!")
    print(f"Archivo final disponible en: {ARCHIVO_SALIDA}")
    print("="*50)
    
    input("Presiona ENTER para cerrar.")
    driver.quit()

if __name__ == "__main__":
    procesar_adp()