from util import *
import protocol

class Connection:
    def __init__(self, name, is_server, title, time, output):
        self.name = name
        self.is_server = is_server
        self.title = title
        self.open_time = time
        self.open = True
        self.out = output
        # keys are ids, values are arrays of objects in the order they are created
        self.db = {}
        self.messages = []
        self.display = Object(self, 1, 'wl_display', None, 0)

    def close(self, time):
        self.open = False
        self.close_time = time

    def set_title(self, title):
        assert isinstance(title, str)
        self.title = title

    def description(self):
        if self.is_server == True:
            txt = 'server'
        elif self.is_server == False:
            txt = 'client'
        else:
            txt = color('1;31', 'unknown type')
        if self.title:
            if self.is_server:
                txt += ' to'
            txt += ' ' + self.title
        return txt

    def look_up_specific(self, obj_id, obj_generation, type_name = None):
        if not obj_id in self.db:
            msg = 'Id ' + str(obj_id) + ' of type ' + str(type_name) + ' not in object database'
            if obj_id > 100000:
                msg += ' (see https://github.com/wmww/wayland-debug/issues/6)'
            raise RuntimeError(msg)
        if obj_generation < 0 or len(self.db[obj_id]) <= obj_generation:
            raise RuntimeError('Invalid generation ' + str(obj_generation) + ' for id ' + str(obj_id))
        obj = self.db[obj_id][obj_generation]
        if type_name and obj.type and not str_matches(type_name, obj.type):
            raise RuntimeError(str(obj) + ' expected to be of type ' + type_name)
        return obj

    def look_up_most_recent(self, obj_id, type_name = None):
        obj_generation = 0
        if obj_id in self.db:
            obj_generation = len(self.db[obj_id]) - 1
        obj = self.look_up_specific(obj_id, obj_generation, type_name)
        # This *would* be a useful warning, except somehow callback.done, delete(callback) (though sent in the right
        # order), arrive to the client in the wrong order. I don't know a better workaround then just turning off the check
        # if not obj.alive:
        #    warning(str(obj) + ' used after destroyed')
        return obj

    def message(self, message):
        if not self.open:
            self.out.warn('Connection ' + self.name + ' (' + self.description() + ') got message ' + str(message) + ' after it had been closed')
            self.open = True
        self.messages.append(message)
        message.resolve(self)
        try:
            if message.name == 'set_app_id':
                self.set_title(message.args[0].value.rsplit(',', 1)[-1])
            elif message.name == 'set_title' and not self.title: # this isn't as good as set_app_id, so don't overwrite
                self.set_title(message.args[0].value)
            elif message.name == 'get_layer_surface':
                self.set_title(message.args[4].value)
        except Exception as e: # Connection name is a non-critical feature, so don't be mean if something goes wrong
            self.out.warning('Could not set connection name: ' + str(e))

class ObjBase:
    def type_str(self):
        if self.type:
            return self.type
        else:
            return color('1;31', '???')
    def id_str(self):
        ret = str(self.id)
        if self.generation == None:
            ret += '.' + color('1;31', '?')
        else:
            ret += '.' + str(self.generation)
        return ret
    def to_str(self):
        return color('1;36' if self.type else '1;31', self.type_str()) + color('37', '@') + color('1;37', self.id_str())
    def lifespan(self):
        if not hasattr(self, 'create_time') or not hasattr(self, 'destroy_time') or self.destroy_time == None:
            return None
        else:
            return self.destroy_time - self.create_time

class Object(ObjBase):
    def __init__(self, connection, obj_id, type_name, parent_obj, create_time):
        assert isinstance(obj_id, int)
        assert obj_id > 0
        assert isinstance(type_name, str)
        assert isinstance(parent_obj, Object) or (parent_obj == None and obj_id == 1)
        assert isinstance(create_time, float) or isinstance(create_time, int)
        if obj_id > 100000:
            connection.out.warn(
                (type_name if type_name else 'Object') +
                ' ID ' + str(obj_id) + ' is probably bigger than it should be (see https://github.com/wmww/wayland-debug/issues/6)')
        if obj_id in connection.db:
            last_obj = connection.db[obj_id][-1]
            if last_obj.alive:
                if type_name == 'wl_registry' and obj_id == 2:
                    msg = ('It looks like multiple Wayland connections were made, without a way to distinguish between them. '
                        + 'Please see https://github.com/wmww/wayland-debug/issues/5 for further details')
                    connection.out.error(msg)
                    raise RuntimeError(msg)
                else:
                    raise RuntimeError('Tried to create object of type '
                        + type_name + ' with the same id as ' + str(last_obj))
        else:
            connection.db[obj_id] = []
        self.generation = len(connection.db[obj_id])
        connection.db[obj_id].append(self)
        self.connection = connection
        self.type = type_name
        self.id = obj_id
        self.parent = parent_obj
        self.create_time = create_time
        self.destroy_time = None
        self.alive = True

    def destroy(self, time):
        self.destroy_time = time
        self.alive = False

    def __str__(self):
        assert self.connection.db[self.id][self.generation] == self, 'Database corrupted'
        return self.to_str()

    class Unresolved(ObjBase):
        def __init__(self, obj_id, type_name):
            assert isinstance(obj_id, int)
            assert obj_id > 0
            assert isinstance(type_name, str) or type_name == None
            self.id = obj_id
            self.generation = None
            self.type = type_name
            self.create_time = 0
        def resolve(self, connection):
            try:
                return connection.look_up_most_recent(self.id, self.type)
            except RuntimeError as e:
                connection.out.warn(str(e))
                return self
        def __str__(self):
            return color('1;31', 'unresolved ') + self.to_str()

class Arg:
    error_color = '1;31'

    class Base:
        def resolve(self, connection, message, index):
            try:
                name = protocol.get_arg_name(message.obj.type, message.name, index)
                if name:
                    self.name = name
            except RuntimeError as e:
                connection.out.warn(e)
        def __str__(self):
            if hasattr(self, 'name'):
                return color('37', self.name + '=') + self.value_to_str()
            else:
                return self.value_to_str()

    # ints, floats, strings and nulls
    class Primitive(Base):
        def __init__(self, value):
            self.value = value

    class Int(Primitive):
        def resolve(self, connection, message, index):
            super().resolve(connection, message, index)
            try:
                labels = protocol.look_up_enum(message.obj.type, message.name, index, self.value)
                if labels:
                    self.labels = labels
            except RuntimeError as e:
                connection.out.warn(e)
        def value_to_str(self):
            assert isinstance(self.value, int)
            if hasattr(self, 'labels'):
                return color('1;34', str(self.value)) + color('34', ':') + color('34', '&').join([color('1;34', i) for i in self.labels])
            else:
                return color('1;34', str(self.value))

    class Float(Primitive):
        def value_to_str(self):
            assert isinstance(self.value, float)
            return color('1;35', str(self.value))

    class String(Primitive):
        def value_to_str(self):
            assert isinstance(self.value, str)
            return color('1;33', repr(self.value))

    class Null(Base):
        def __init__(self, type_=None):
            assert isinstance(type_, str) or type_ == None
            self.type = type_
        def resolve(self, connection, message, index):
            super().resolve(connection, message, index)
            if not self.type:
                try:
                    self.type = protocol.look_up_interface(message.obj.type, message.name, index)
                except RuntimeError as e:
                    connection.out.warn(e)

        def value_to_str(self):
            return color('1;37', 'null ' + (self.type if self.type else '??'))

    class Object(Base):
        def __init__(self, obj, is_new):
            assert isinstance(obj, ObjBase)
            assert isinstance(is_new, bool)
            self.obj = obj
            self.is_new = is_new
        def set_type(self, new_type):
            if isinstance(self.obj, Object.Unresolved) and self.obj.type == None:
                self.obj.type = new_type
            assert new_type == self.obj.type, 'Object arg already has type ' + self.obj.type + ', so can not be set to ' + new_type
        def resolve(self, connection, message, index):
            super().resolve(connection, message, index)
            if isinstance(self.obj, Object.Unresolved):
                if self.is_new:
                    try:
                        Object(connection, self.obj.id, self.obj.type, message.obj, message.timestamp)
                    except RuntimeError as e:
                        connection.out.error(e)
                self.obj = self.obj.resolve(connection)
        def value_to_str(self):
            return (color('1;32', 'new ') if self.is_new else '') + str(self.obj)

    class Fd(Base):
        def __init__(self, value):
            assert isinstance(value, int)
            self.value = value
        def value_to_str(self):
            return color('36', 'fd ' + str(self.value))

    class Array(Base):
        def __init__(self, values=None):
            if isinstance(values, list):
                for i in values:
                    assert isinstance(i, Arg.Base)
            else:
                assert values == None
            self.values = values
        def resolve(self, connection, message, index):
            super().resolve(connection, message, index)
            if self.values != None:
                for v in self.values:
                    v.resolve(connection, message, index)
                    if hasattr(v, 'name'):
                        del v.name # hack to stop names appearing in every array element
        def value_to_str(self):
            if self.values != None:
                return color('1;37', '[') + color('1;37', ', ').join([str(v) for v in self.values]) + color('1;37', ']')
            else:
                return color('1;37', '[...]')

    class Unknown(Base):
        def __init__(self, string=None):
            assert isinstance(string, str) or string == None
            self.string = string
        def value_to_str(self):
            if self.string == None:
                return color(Arg.error_color, '?')
            else:
                return color(Arg.error_color, 'Unknown: ' + repr(self.string))

class Message:
    base_time = None

    def __init__(self, abs_time, obj, sent, name, args):
        assert isinstance(abs_time, float) or isinstance(abs_time, int)
        assert isinstance(obj, ObjBase)
        assert isinstance(sent, bool)
        assert isinstance(name, str)
        for arg in args:
            assert isinstance(arg, Arg.Base)
        if Message.base_time == None:
            Message.base_time = abs_time
        self.timestamp = abs_time - Message.base_time
        self.obj = obj
        self.sent = sent
        self.name = name
        self.args = args
        self.destroyed_obj = None

    def resolve(self, connection):
        if isinstance(self.obj, Object.Unresolved):
            self.obj = self.obj.resolve(connection)
        if self.obj.type == 'wl_registry' and self.name == 'bind':
            assert isinstance(self.args[3], Arg.Object)
            self.args[3].set_type(self.args[1].value)
        if self.obj == connection.display and self.name == 'delete_id' and len(self.args) > 0:
            self.destroyed_obj = connection.look_up_most_recent(self.args[0].value, None)
            self.destroyed_obj.destroy(self.timestamp)
        for i, arg in enumerate(self.args):
            arg.resolve(connection, self, i)

    def used_objects(self):
        result = []
        for i in self.args:
            if isinstance(i, Arg.Object):
                result.append(i.obj)
        if self.destroyed_obj:
            result.append(self.destroyed_obj)
        return result

    def __str__(self):
        destroyed = ''
        if self.destroyed_obj:
            destroyed = (
                color(timestamp_color, ' -- ') +
                color('1;31', 'destroyed ') +
                str(self.destroyed_obj) +
                color(timestamp_color, ' after {:0.4f}s'.format(self.destroyed_obj.lifespan())))
        return (
            (color('37', '→ ') if self.sent else '') +
            str(self.obj) + ' ' +
            color(message_color, self.name) + color(timestamp_color, '(') +
            color(timestamp_color, ', ').join([str(i) for i in self.args]) + color(timestamp_color, ')') +
            destroyed +
            (color(timestamp_color, ' ↲') if not self.sent else ''))

    def show(self, out):
        out.show(color('37', '{:7.4f}'.format(self.timestamp)) + ' ' + str(self))

if __name__ == '__main__':
    print('File meant to be imported, not run')
    exit(1)
