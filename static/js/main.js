// =====================================================
// UTILIDADES GENERALES
// =====================================================
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
}

function contarDiasHabilesEstimado(fechaInicioStr, fechaFinStr) {
    if (!fechaInicioStr || !fechaFinStr) return null;
    const inicio = new Date(fechaInicioStr + 'T00:00:00');
    const fin = new Date(fechaFinStr + 'T00:00:00');
    if (isNaN(inicio) || isNaN(fin) || fin < inicio) return null;
    let dias = 0;
    const actual = new Date(inicio);
    while (actual <= fin) {
        const diaSemana = actual.getDay();
        if (diaSemana !== 0 && diaSemana !== 6) dias++;
        actual.setDate(actual.getDate() + 1);
    }
    return dias;
}

async function chequearSuperposiciones(fechaInicio, fechaFin, contenedorId) {
    const contenedor = document.getElementById(contenedorId);
    if (!contenedor) return;
    if (!fechaInicio || !fechaFin) {
        contenedor.hidden = true;
        return;
    }
    try {
        const res = await fetch(`/api/superposiciones?fecha_inicio=${fechaInicio}&fecha_fin=${fechaFin}`);
        const data = await res.json();
        if (data.agentes && data.agentes.length > 0) {
            contenedor.textContent = `⚠️ Ya hay compañeros con licencia aprobada en esas fechas: ${data.agentes.join(', ')}.`;
            contenedor.hidden = false;
        } else {
            contenedor.hidden = true;
        }
    } catch {
        contenedor.hidden = true;
    }
}

const Utils = {
    showFlashMessage(message, category) {
        const container = document.querySelector('.flash-container');
        if (!container) return;

        const alertDiv = document.createElement('div');
        alertDiv.className = `alert-${category} top-alert`;
        alertDiv.textContent = message;
        container.prepend(alertDiv);

        setTimeout(() => {
            alertDiv.style.opacity = '1';
            alertDiv.style.transform = 'translateY(0)';
        }, 10);

        setTimeout(() => {
            alertDiv.style.opacity = '0';
            alertDiv.style.transform = 'translateY(-20px)';
            setTimeout(() => alertDiv.remove(), 500);
        }, 5000);
    }
};

// =====================================================
// GESTIÓN DE MODALES
// =====================================================
const ModalManager = {
    init() {
    },

    open(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'block';
    },

    close(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'none';
    },

    setupCloseButton(buttonId, modalId) {
        const button = document.getElementById(buttonId);
        if (button) {
            button.addEventListener('click', () => this.close(modalId));
        }
    }
};

// =====================================================
// MENÚ DESPLEGABLE DE USUARIO
// =====================================================
const UserMenu = {
    init() {
        const menuBtn = document.getElementById('userMenuBtn');
        const dropdown = document.getElementById('userMenuDropdown');

        if (!menuBtn || !dropdown) return;

        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        });

        window.addEventListener('click', (e) => {
            if (!menuBtn.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });
    }
};

// =====================================================
// GESTIÓN DE "OLVIDASTE CONTRASEÑA"
// =====================================================
const ForgotPassword = {
    init() {
        const link = document.getElementById('forgotPasswordLink');
        if (!link) return;

        link.addEventListener('click', (e) => {
            e.preventDefault();
            Swal.fire({
                title: 'Restablecer Contraseña',
                html: 'Para restablecer tu contraseña, contactá a <strong>Recursos Humanos</strong> para recibir una nueva clave temporal.',
                icon: 'info',
                confirmButtonText: 'Entendido',
                confirmButtonColor: '#007bff',
            });
        });
    }
};

// =====================================================
// DASHBOARD DEL AGENTE (Licencias)
// =====================================================
const AgentDashboard = {
    init() {
        this.setupRequestModal();
        this.setupDetailModal();
        this.setupDiasHabilesPreview();
        this.setupProximosFeriadosModal();
    },

    setupProximosFeriadosModal() {
        const openBtn = document.getElementById('openProximosFeriadosBtn');
        if (!openBtn) return;
        openBtn.addEventListener('click', () => ModalManager.open('proximosFeriadosModal'));
        ModalManager.setupCloseButton('closeProximosFeriadosBtn', 'proximosFeriadosModal');
    },

    setupRequestModal() {
        const openBtn = document.getElementById('openModalBtn');
        const modal = document.getElementById('requestModal');

        if (!openBtn || !modal) return;

        openBtn.addEventListener('click', (e) => {
            e.preventDefault();
            ModalManager.open('requestModal');
            const dropdown = document.getElementById('userMenuDropdown');
            if (dropdown) dropdown.classList.remove('show');
        });

        ModalManager.setupCloseButton('closeRequestModalBtn', 'requestModal');
    },

    setupDetailModal() {
        const modal = document.getElementById('agentSolicitudDetailModal');
        if (!modal) return;

        ModalManager.setupCloseButton('closeAgentDetailModalBtn', 'agentSolicitudDetailModal');

        document.querySelectorAll('.view-agent-details-btn').forEach(button => {
            button.addEventListener('click', function() {
                const data = this.dataset;
                document.getElementById('agent-detail-tipo').textContent = data.tipo;
                document.getElementById('agent-detail-fecha').textContent = data.fecha;
                document.getElementById('agent-detail-fecha-fin').textContent = data.fechaFin;
                document.getElementById('agent-detail-dias').textContent = data.dias;
                document.getElementById('agent-detail-estado').textContent = data.estado;
                document.getElementById('agent-detail-comentario-agente').textContent = data.comentarioAgente;
                document.getElementById('agent-detail-comentario-admin').textContent = data.comentarioAdmin;
                ModalManager.open('agentSolicitudDetailModal');
            });
        });
    },

    setupDiasHabilesPreview() {
        const fechaInicio = document.getElementById('fecha_inicio');
        const fechaFin = document.getElementById('fecha_fin');
        const preview = document.getElementById('diasHabilesPreview');
        if (!fechaInicio || !fechaFin) return;

        const actualizar = () => {
            const dias = contarDiasHabilesEstimado(fechaInicio.value, fechaFin.value);
            if (preview) {
                if (dias !== null) {
                    preview.textContent = `≈ ${dias} día(s) hábil(es) estimado(s) (sin contar feriados; el sistema los descuenta al enviar la solicitud).`;
                    preview.hidden = false;
                } else {
                    preview.hidden = true;
                }
            }
            chequearSuperposiciones(fechaInicio.value, fechaFin.value, 'superposicionAlerta');
        };
        fechaInicio.addEventListener('change', actualizar);
        fechaFin.addEventListener('change', actualizar);
    }
};

// =====================================================
// PANEL DE ADMINISTRACIÓN - ACORDEONES
// =====================================================
const AccordionManager = {
    init() {
        document.querySelectorAll('.section-header').forEach(header => {
            header.addEventListener('click', () => {
                const content = header.nextElementSibling;
                const toggleBtn = header.querySelector('.toggle-btn');

                document.querySelectorAll('.section-content').forEach(other => {
                    if (other !== content && other.style.display === 'block') {
                        other.style.display = 'none';
                        other.previousElementSibling.querySelector('.toggle-btn').classList.remove('is-open');
                    }
                });

                const isVisible = content.style.display === 'block';
                content.style.display = isVisible ? 'none' : 'block';
                toggleBtn.classList.toggle('is-open', !isVisible);
            });
        });
    }
};

// =====================================================
// GESTIÓN DE AGENTES (ADMIN)
// =====================================================
const AgentManagement = {
    init() {
        this.setupCreateModal();
        this.setupEditModal();
        this.setupToggleStatus();
    },

    setupCreateModal() {
        const openBtn = document.getElementById('openCreateAgentModalBtn');
        if (!openBtn) return;
        openBtn.addEventListener('click', () => ModalManager.open('createAgentModal'));
        ModalManager.setupCloseButton('closeCreateAgentModalBtn', 'createAgentModal');
    },

    setupEditModal() {
        ModalManager.setupCloseButton('closeEditAgentModalBtn', 'editAgentModal');

        document.querySelectorAll('.edit-agent-btn').forEach(button => {
            button.addEventListener('click', function() {
                const data = this.dataset;
                const form = document.getElementById('editAgentForm');

                form.action = `/admin/editar-agente/${data.id}`;
                document.getElementById('edit-nombre').value = data.nombre;
                document.getElementById('edit-usuario').value = data.usuario;
                document.getElementById('edit-lao').value = data.cupoLao;
                document.getElementById('edit-invierno').value = data.cupoInvierno;
                document.getElementById('edit-comp').value = data.cupoCompensatorio;
                document.getElementById('edit-examen').value = data.cupoExamenEstudio;
                document.getElementById('edit-nueva-clave').value = '';
                document.getElementById('edit-examen-habilitado').checked = (data.examenHabilitado === 'true');
                document.getElementById('edit-es-admin').checked = (data.esAdmin === 'true');

                ModalManager.open('editAgentModal');
            });
        });
    },

    setupToggleStatus() {
        document.querySelectorAll('.toggle-agent-btn').forEach(button => {
            button.addEventListener('click', async function(e) {
                e.preventDefault();
                const agentId = this.dataset.id;
                const btn = this;
                btn.disabled = true;
                btn.textContent = '...';

                try {
                    const res = await fetch(`/admin/toggle-agente/${agentId}`, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': getCsrfToken() }
                    });
                    const data = await res.json();
                    if (data.success) {
                        const row = document.getElementById(`agente-row-${agentId}`);
                        const badge = row.querySelector('.status-badge');
                        badge.textContent = data.nuevo_estado_texto;
                        badge.className = `status-badge ${data.nuevo_estado_clase}`;
                        btn.textContent = data.nuevo_boton_texto;
                        btn.className = `action-btn ${data.nuevo_boton_clase} toggle-agent-btn`;
                        Utils.showFlashMessage(data.message, 'success');
                    } else {
                        Utils.showFlashMessage(data.error, 'danger');
                    }
                } catch {
                    Utils.showFlashMessage('Error de red', 'danger');
                } finally {
                    btn.disabled = false;
                }
            });
        });
    }
};

// =====================================================
// GESTIÓN DE SOLICITUDES (ADMIN)
// =====================================================
const RequestManagement = {
    init() {
        this.setupTabs();
        this.setupDetailModal();
    },

    setupTabs() {
        document.querySelectorAll('.tabs').forEach(container => {
            const buttons = container.querySelectorAll('.tab-button');
            buttons.forEach(btn => {
                btn.addEventListener('click', () => {
                    buttons.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    const tabId = btn.dataset.tab;
                    const section = btn.closest('.section-content');
                    section.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
                    section.querySelector(`#${tabId}`).classList.add('active');
                });
            });
        });
    },

    setupDetailModal() {
        ModalManager.setupCloseButton('closeDetailModalBtn', 'solicitudDetailModal');
        document.querySelectorAll('.view-details-btn').forEach(button => {
            button.addEventListener('click', function() {
                const d = this.dataset;
                document.getElementById('detail-agente').textContent = d.agente;
                document.getElementById('detail-tipo').textContent = d.tipo;
                document.getElementById('detail-fecha').textContent = d.fecha;
                document.getElementById('detail-fecha-fin').textContent = d.fechaFin;
                document.getElementById('detail-dias').textContent = d.dias;
                document.getElementById('detail-comentario').textContent = d.comentario;
                const categoriaSelect = document.getElementById('detail-categoria-select');
                if (categoriaSelect && d.categoria) categoriaSelect.value = d.categoria;
                document.getElementById('approve-form').action = `/aprobar_solicitud/${d.id}`;
                document.getElementById('reject-form').action = `/rechazar_solicitud/${d.id}`;
                ModalManager.open('solicitudDetailModal');
            });
        });
        this.setupAdminComments();
    },

    setupAdminComments() {
        const commentText = document.getElementById('comentario_admin_text');
        const categoriaSelect = document.getElementById('detail-categoria-select');
        ['approve-form', 'reject-form'].forEach(id => {
            const form = document.getElementById(id);
            if (form) {
                form.addEventListener('submit', function() {
                    form.querySelector('input[name="comentario_admin"]').value = commentText.value;
                    const categoriaInput = form.querySelector('input[name="categoria"]');
                    if (categoriaInput && categoriaSelect) categoriaInput.value = categoriaSelect.value;
                });
            }
        });
    }
};

// =====================================================
// FERIADOS (ADMIN)
// =====================================================
const FeriadosManagement = {
    init() {
        const openAdd = document.getElementById('openAddFeriadoModalBtn');
        if (openAdd) openAdd.addEventListener('click', () => ModalManager.open('addFeriadoModal'));
        ModalManager.setupCloseButton('closeAddFeriadoModalBtn', 'addFeriadoModal');

        const openImport = document.getElementById('openImportarFeriadosModalBtn');
        if (openImport) openImport.addEventListener('click', () => ModalManager.open('importarFeriadosModal'));
        ModalManager.setupCloseButton('closeImportarFeriadosModalBtn', 'importarFeriadosModal');

        ModalManager.setupCloseButton('closeEditFeriadoModalBtn', 'editFeriadoModal');
        document.querySelectorAll('.edit-feriado-btn').forEach(btn => {
            btn.addEventListener('click', function () {
                const d = this.dataset;
                const form = document.getElementById('editFeriadoForm');
                form.action = `/admin/feriados/editar/${d.id}`;
                document.getElementById('edit-feriado-fecha').value = d.fecha;
                document.getElementById('edit-feriado-descripcion').value = d.descripcion;
                document.getElementById('edit-feriado-tipo').value = d.tipo;
                ModalManager.open('editFeriadoModal');
            });
        });
    }
};

// =====================================================
// PERÍODOS DE VEDA (ADMIN)
// =====================================================
const VedaManagement = {
    init() {
        const openBtn = document.getElementById('openAddVedaModalBtn');
        if (openBtn) openBtn.addEventListener('click', () => ModalManager.open('addVedaModal'));
        ModalManager.setupCloseButton('closeAddVedaModalBtn', 'addVedaModal');
    }
};

// =====================================================
// CARGA DE OFICIO (ADMIN)
// =====================================================
const CargaOficioManagement = {
    init() {
        const openBtn = document.getElementById('openCargaOficioModalBtn');
        if (openBtn) openBtn.addEventListener('click', () => ModalManager.open('cargaOficioModal'));
        ModalManager.setupCloseButton('closeCargaOficioModalBtn', 'cargaOficioModal');

        // Evita el doble-submit (doble click o Enter repetido): al enviar,
        // se bloquea el botón para que un segundo click no dispare una
        // segunda carga de oficio idéntica mientras la primera todavía
        // está en camino al servidor.
        const form = document.querySelector('#cargaOficioModal form');
        if (form) {
            form.addEventListener('submit', () => {
                const btn = form.querySelector('button[type="submit"]');
                if (btn) {
                    btn.disabled = true;
                    btn.textContent = 'Registrando...';
                }
            });
        }
    }
};

// =====================================================
// CIERRE DE EJERCICIO (ADMIN)
// =====================================================
const CierreEjercicioManagement = {
    init() {
        const btn = document.getElementById('openCerrarEjercicioBtn');
        if (!btn) return;
        btn.addEventListener('click', () => {
            Swal.fire({
                title: 'Cerrar Ejercicio',
                html: 'Los saldos <strong>no gozados</strong> de las 4 categorías de todos los agentes vencerán y se reiniciarán a 0. Los cupos asignados no se modifican.<br><br>Si hay solicitudes pendientes sin resolver, la operación se bloqueará hasta que las gestiones.<br><br>Esta acción no se puede deshacer. ¿Confirmar?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Cerrar Ejercicio',
                confirmButtonColor: '#dc3545',
            }).then(r => {
                if (r.isConfirmed) {
                    document.getElementById('cerrarEjercicioForm').submit();
                }
            });
        });
    }
};

// =====================================================
// EDITOR DE TEXTO ENRIQUECIDO (mensajes de Novedades)
// =====================================================
const RichTextEditor = {
    init() {
        document.querySelectorAll('.rich-editor').forEach(editor => {
            const textarea = document.getElementById(editor.dataset.textarea);
            if (!textarea) return;

            const sincronizar = () => { textarea.value = editor.innerHTML.trim(); };
            editor.addEventListener('input', sincronizar);

            const form = editor.closest('form');
            if (form) {
                form.addEventListener('submit', (e) => {
                    sincronizar();
                    if (!editor.textContent.trim()) {
                        e.preventDefault();
                        editor.classList.add('rich-editor-error');
                        editor.focus();
                    } else {
                        editor.classList.remove('rich-editor-error');
                    }
                });
            }
        });

        document.querySelectorAll('.rich-toolbar').forEach(toolbar => {
            const editor = document.getElementById(toolbar.dataset.target);
            if (!editor) return;
            toolbar.querySelectorAll('.rich-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    editor.focus();
                    document.execCommand(btn.dataset.command, false, null);
                    editor.dispatchEvent(new Event('input'));
                });
            });
        });
    },

    cargarContenido(editorId, html) {
        const editor = document.getElementById(editorId);
        if (!editor) return;
        editor.innerHTML = html || '';
        editor.classList.remove('rich-editor-error');
        editor.dispatchEvent(new Event('input'));
    }
};

// =====================================================
// BUSCADOR / FILTRO DE TABLAS (ADMIN)
// =====================================================
const TableFilter = {
    init() {
        document.querySelectorAll('.filter-input').forEach(input => {
            const tablas = document.querySelectorAll(input.dataset.filterTarget);
            if (!tablas.length) return;
            input.addEventListener('input', () => {
                const query = input.value.trim().toLowerCase();
                tablas.forEach(tabla => this.filtrarTabla(tabla, query));
            });
        });
    },

    filtrarTabla(tabla, query) {
        const tbody = tabla.querySelector('tbody');
        if (!tbody) return;
        const filas = tbody.querySelectorAll('tr[data-filter-row]');
        let visibles = 0;

        filas.forEach(fila => {
            const coincide = !query || fila.textContent.toLowerCase().includes(query);
            fila.style.display = coincide ? '' : 'none';
            if (coincide) visibles++;
        });

        let filaVacia = tbody.querySelector('.filter-empty-row');
        if (query && visibles === 0) {
            if (!filaVacia) {
                const columnas = tabla.querySelectorAll('thead th').length || 1;
                filaVacia = document.createElement('tr');
                filaVacia.className = 'filter-empty-row';
                filaVacia.innerHTML = `<td colspan="${columnas}" style="text-align:center; color:#6c757d;">No se encontraron resultados.</td>`;
                tbody.appendChild(filaVacia);
            }
            filaVacia.style.display = '';
        } else if (filaVacia) {
            filaVacia.style.display = 'none';
        }
    }
};

// =====================================================
// GESTIÓN DE NOVEDADES (ADMIN)
// =====================================================
const NewsManagement = {
    init() {
        this.setupAddModal();
        this.setupEditModal();
    },

    setupAddModal() {
        const openBtn = document.getElementById('openNovedadModalBtn');
        if (!openBtn) return;
        openBtn.addEventListener('click', () => ModalManager.open('addNovedadModal'));
        ModalManager.setupCloseButton('closeAddModalBtn', 'addNovedadModal');
    },

    setupEditModal() {
        ModalManager.setupCloseButton('closeEditModalBtn', 'editNovedadModal');
        document.querySelectorAll('.edit-novedad-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const d = this.dataset;
                const form = document.getElementById('editNovedadForm');
                form.action = `/admin/editar-novedad/${d.id}`;
                document.getElementById('edit-titulo').value = d.titulo;
                RichTextEditor.cargarContenido('edit-mensaje-editor', d.mensaje);
                ModalManager.open('editNovedadModal');
            });
        });
    }
};

// =====================================================
// CONFIRMACIONES CON SWEETALERT2
// =====================================================
const ConfirmationManager = {
    init() {
        document.body.addEventListener('submit', (e) => {
            if (e.target.classList.contains('rectify-form')) {
                this.handleRectify(e);
            } else if (e.target.classList.contains('delete-novedad-form')) {
                this.handleDeleteNews(e);
            } else if (e.target.classList.contains('delete-agent-form')) {
                this.handleDeleteAgent(e);
            } else if (e.target.classList.contains('delete-solicitud-form')) {
                this.handleDeleteSolicitud(e);
            }
        });
    },

    handleDeleteSolicitud(e) {
        e.preventDefault();
        const form = e.target;
        const name = form.closest('tr').querySelector('td').textContent.trim();
        Swal.fire({
            title: '¿Eliminar esta solicitud?',
            html: `La solicitud pendiente de <strong>${name}</strong> se eliminará y se liberarán los días reservados. No se puede revertir.`,
            icon: 'warning', showCancelButton: true, confirmButtonText: 'Eliminar', confirmButtonColor: '#dc3545',
        }).then(r => { if (r.isConfirmed) form.submit(); });
    },

    handleRectify(e) {
        e.preventDefault();
        const form = e.target;
        let msg = "¿Mover esta solicitud a 'Pendientes'?";
        if (form.closest('#aprobadas')) msg = "Los días serán devueltos al agente. ¿Continuar?";
        Swal.fire({ title: 'Confirmar Acción', text: msg, icon: 'warning', showCancelButton: true })
            .then(r => { if (r.isConfirmed) form.submit(); });
    },

    handleDeleteNews(e) {
        e.preventDefault();
        const form = e.target;
        Swal.fire({ title: '¿Eliminar esta novedad?', text: "No se puede revertir.", icon: 'warning', showCancelButton: true })
            .then(r => { if (r.isConfirmed) form.submit(); });
    },

    handleDeleteAgent(e) {
        e.preventDefault();
        const form = e.target;
        const name = form.closest('tr').querySelector('td').textContent.trim();
        Swal.fire({ title: 'Eliminar agente', html: `<strong>${name}</strong> será eliminado.`, icon: 'error', showCancelButton: true })
            .then(r => { if (r.isConfirmed) form.submit(); });
    }
};

// =====================================================
// INICIALIZACIÓN PRINCIPAL
// =====================================================
document.addEventListener('DOMContentLoaded', () => {
    ModalManager.init();
    UserMenu.init();
    ForgotPassword.init();
    AgentDashboard.init();
    AccordionManager.init();
    AgentManagement.init();
    RequestManagement.init();
    FeriadosManagement.init();
    VedaManagement.init();
    CargaOficioManagement.init();
    CierreEjercicioManagement.init();
    RichTextEditor.init();
    TableFilter.init();
    NewsManagement.init();
    ConfirmationManager.init();
    CalendarioManager.init();
    PreviewRequests.init();

});

document.addEventListener("DOMContentLoaded", () => {
  const previewBtn = document.getElementById("previewLicenciaBtn");
  const modal = document.getElementById("previewLicenciaModal");
  const closeBtn = document.getElementById("closePreviewLicenciaBtn");
  const editBtn = document.getElementById("editLicenciaBtn");
  const confirmBtn = document.getElementById("confirmLicenciaBtn");

  if (!previewBtn) return;

  previewBtn.addEventListener("click", () => {
    const tipoSelect = document.getElementById("tipo_licencia");
    document.getElementById("prevLicTipo").textContent = tipoSelect.options[tipoSelect.selectedIndex].text;
    document.getElementById("prevLicInicio").textContent = document.getElementById("fecha_inicio").value;
    document.getElementById("prevLicFin").textContent = document.getElementById("fecha_fin").value;
    document.getElementById("prevLicComentario").textContent = document.getElementById("comentario_agente").value || "-";
    modal.style.display = "block";
  });

  // Cerrar modal
  closeBtn.onclick = editBtn.onclick = () => modal.style.display = "none";

  // ✅ Enviar realmente el formulario
  confirmBtn.addEventListener("click", () => {
    modal.style.display = "none";
    // Busca el formulario más cercano al botón de previsualizar
    const form = previewBtn.closest("form");
    if (form) {
      form.submit(); // ✅ Envío seguro del formulario
    } else {
      alert("No se encontró el formulario. Verifica la estructura del HTML.");
    }
  });

});

// ===============================
// MODAL EDITAR SOLICITUD
// ===============================
document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("editarSolicitudModal");
  const closeBtn = document.getElementById("closeEditarSolicitudBtn");
  const cancelBtn = document.getElementById("cancelarEdicionBtn");

  if (!modal) return;

  window.abrirModalEditarSolicitud = (id, tipo, fechaInicio, fechaFin, comentario) => {
    document.getElementById("edit_id").value = id;
    document.getElementById("edit_tipo_licencia").value = tipo;
    document.getElementById("edit_fecha_inicio").value = fechaInicio;
    document.getElementById("edit_fecha_fin").value = fechaFin;
    document.getElementById("edit_comentario_agente").value = comentario;
    modal.style.display = "block";
  };

  const cerrarModal = () => (modal.style.display = "none");

  closeBtn.onclick = cerrarModal;
  cancelBtn.onclick = cerrarModal;
});

function confirmarEliminarSolicitud(idSolicitud) {
    if (confirm("¿Estás seguro de que querés eliminar esta solicitud? Esta acción no se puede deshacer.")) {
        fetch(`/eliminar_solicitud/${idSolicitud}`, {
            method: "POST",
            headers: { 'X-CSRFToken': getCsrfToken() }
        })
        .then(response => {
            if (response.ok) {
                location.reload(); // refresca la página para reflejar el cambio
            } else {
                alert("Ocurrió un error al eliminar la solicitud.");
            }
        })
        .catch(() => alert("Error de conexión con el servidor."));
    }
}

// =====================================================
// CALENDARIO DE LICENCIAS
// =====================================================
const CalendarioManager = {
    mesActual: new Date().getMonth() + 1,
    añoActual: new Date().getFullYear(),

    init() {
        const openBtn = document.getElementById('openCalendarioBtn');
        if (!openBtn) return;

        openBtn.addEventListener('click', (e) => {
            e.preventDefault();
            this.abrirCalendario();
            const dropdown = document.getElementById('userMenuDropdown');
            if (dropdown) dropdown.classList.remove('show');
        });

        ModalManager.setupCloseButton('closeCalendarioBtn', 'calendarioModal');

        document.getElementById('mesAnteriorBtn')?.addEventListener('click', () => {
            this.cambiarMes(-1);
        });

        document.getElementById('mesSiguienteBtn')?.addEventListener('click', () => {
            this.cambiarMes(1);
        });
    },

    abrirCalendario() {
        ModalManager.open('calendarioModal');
        this.cargarMes(this.añoActual, this.mesActual);
    },

    cambiarMes(delta) {
        this.mesActual += delta;
        if (this.mesActual > 12) {
            this.mesActual = 1;
            this.añoActual++;
        } else if (this.mesActual < 1) {
            this.mesActual = 12;
            this.añoActual--;
        }
        this.cargarMes(this.añoActual, this.mesActual);
    },

    async cargarMes(año, mes) {
        const meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                       'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

        document.getElementById('mesActualTexto').textContent = `${meses[mes - 1]} ${año}`;

        try {
            const response = await fetch(`/api/calendario/${año}/${mes}`);
            const data = await response.json();

            if (data.error) {
                Utils.showFlashMessage('Error al cargar el calendario', 'danger');
                return;
            }

            this.renderizarCalendario(año, mes, data.eventos, data.feriados);
            this.renderizarLista(data.eventos);
        } catch (error) {
            Utils.showFlashMessage('Error de conexión', 'danger');
        }
    },

    renderizarCalendario(año, mes, eventos, feriados) {
        const grid = document.getElementById('calendarioGrid');
        grid.innerHTML = '';

        // Encabezados de días
        const dias = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
        dias.forEach(dia => {
            const header = document.createElement('div');
            header.className = 'calendario-dia-nombre';
            header.textContent = dia;
            grid.appendChild(header);
        });

        // Mapa de feriados del mes (fecha -> descripción)
        const feriadosPorFecha = {};
        (feriados || []).forEach(f => { feriadosPorFecha[f.fecha] = f.descripcion; });

        // Calcular días del mes
        const primerDia = new Date(año, mes - 1, 1).getDay();
        const diasEnMes = new Date(año, mes, 0).getDate();

        // Días vacíos al inicio
        for (let i = 0; i < primerDia; i++) {
            const empty = document.createElement('div');
            empty.className = 'calendario-dia vacio';
            grid.appendChild(empty);
        }

        // Días del mes
        for (let dia = 1; dia <= diasEnMes; dia++) {
            const fechaActual = `${año}-${String(mes).padStart(2, '0')}-${String(dia).padStart(2, '0')}`;
            const celda = document.createElement('div');
            celda.className = 'calendario-dia';

            if (feriadosPorFecha[fechaActual]) {
                celda.classList.add('feriado');
                celda.title = feriadosPorFecha[fechaActual];
            }

            const numero = document.createElement('div');
            numero.className = 'calendario-dia-numero';
            numero.textContent = dia;
            celda.appendChild(numero);

            if (feriadosPorFecha[fechaActual]) {
                const etiquetaFeriado = document.createElement('div');
                etiquetaFeriado.className = 'calendario-feriado-etiqueta';
                etiquetaFeriado.textContent = feriadosPorFecha[fechaActual];
                celda.appendChild(etiquetaFeriado);
            }

            // El rango fecha_inicio-fecha_fin de una licencia puede atravesar
            // fines de semana o feriados (son días que ya no eran hábiles, no
            // se "usaron"). Por eso el evento solo se dibuja si el día en
            // cuestión es hábil: de lunes a viernes y sin feriado cargado.
            const diaSemana = new Date(año, mes - 1, dia).getDay();
            const esDiaHabil = diaSemana !== 0 && diaSemana !== 6 && !feriadosPorFecha[fechaActual];

            if (esDiaHabil) {
                eventos.forEach(evento => {
                    if (fechaActual >= evento.fecha_inicio && fechaActual <= evento.fecha_fin) {
                        const eventoDiv = document.createElement('div');
                        eventoDiv.className = 'calendario-evento';
                        eventoDiv.textContent = evento.agente;
                        eventoDiv.title = `${evento.agente} - Ausente/Licencia`;
                        celda.appendChild(eventoDiv);
                    }
                });
            }

            grid.appendChild(celda);
        }
    },

    renderizarLista(eventos) {
        const contenedor = document.getElementById('licenciasContenido');

        if (eventos.length === 0) {
            contenedor.innerHTML = '<p style="color: #6c757d; text-align: center;">No hay licencias programadas para este mes.</p>';
            return;
        }

        contenedor.innerHTML = '';
        eventos.forEach(evento => {
            const item = document.createElement('div');
            item.className = 'licencia-item';
            item.innerHTML = `
                <strong>${evento.agente}</strong>
                <p><strong>Ausente:</strong> ${this.formatearFecha(evento.fecha_inicio)} al ${this.formatearFecha(evento.fecha_fin)} (${evento.dias_totales} días)</p>
            `;
            contenedor.appendChild(item);
        });
    },

    formatearFecha(fechaStr) {
        const [año, mes, dia] = fechaStr.split('-');
        return `${dia}/${mes}/${año}`;
    }
};

// =====================================================
// PREVISUALIZACIÓN DE SOLICITUDES (placeholder de compatibilidad)
// =====================================================
const PreviewRequests = {
    init() {
        // La previsualización de licencia se maneja en el bloque dedicado más
        // arriba en este archivo; este objeto queda como punto de extensión.
    }
};
