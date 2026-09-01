#Se redefinen las funciones para usuario

from BASE_ROLE import BASE_ROLE

class ROLE_USER(BASE_ROLE):

    def biblioteca_consulta(self):
        pass

    def dashboard_select_proyecto(self):
        pass

    def dashboard_indicador_aceptacion(self):
        pass

    ##################
    ##################
    ##################
    def proyecto_generar_termino(self):
        raise PermissionError("No tienes permisos para generar términos")

    def proyecto_ejecutar(self):
        raise PermissionError("No tienes permisos para ejecutar proyectos")

    def biblioteca_descargar(self):
        raise PermissionError("No tienes permisos para descargar archivos")

    def biblioteca_eliminar(self):
        raise PermissionError("No tienes permisos para eliminar archivos")

    def dashboard_filter_geo(self):
        raise PermissionError("No tienes permisos para filtrar por geolocalización")

    #ver esta función qué hace para saber si es como de js o cosa de backend
    def dashboard_limpiar(self):
        pass

    def dashboard_filter_topic(self):
        raise PermissionError("No tienes permisos para filtrar por topics")

    def dashboard_prediccion(self):
        raise PermissionError("No tienes permisos para ejecutar predicciones")

    def dashboard_generar_alertas(self):
        raise PermissionError("No tienes permisos para generar alertas")

    #Estoy en duda si el usuario "user" debería o no hacerlo tener estos permisos
    def ajustes_update_datos(self):
        raise PermissionError("No tienes permisos para actualizar datos del user")